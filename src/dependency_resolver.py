import abc
import json
import logging
import os
import time
import zipfile
from enum import unique, IntEnum
from typing import Optional, List
from remotezip import RemoteZip, RemoteIOError
import dataset
import requests
from dataset import Database, Table
from furl import furl
from web_apis import ApiHelper


@unique
class SkipReason(IntEnum):
	ZERO_DOWNLOADS = 0,
	DOWNLOAD_TOO_LARGE = 2,  # legacy, we now only download the manifest from the mod-pack which is always small enough
	DOWNLOAD_ERROR = 3,
	FILE_PARSING_ERROR = 4,
	MOD_DISTRIBUTION_NOT_ALLOWED = 5  # new, projects with this flag can't be downloaded via the CF Api


class GetRedirectedUrlError(Exception):
	pass


class FileIdentifier:
	def __init__(self, project_id: int, file_id: int):
		self._project_id: int = project_id
		self._file_id: int = file_id

	@property
	def project_id(self):
		return self._project_id

	@property
	def file_id(self):
		return self._file_id


class DependencyResolverInterface(metaclass=abc.ABCMeta):

	def __enter__(self):
		return self

	@abc.abstractmethod
	def __exit__(self, exc_type, exc_val, exc_tb):
		raise NotImplementedError

	@abc.abstractmethod
	def is_file_depending_on_project(self, file: FileIdentifier, project_id: int) -> bool:
		raise NotImplementedError

	@abc.abstractmethod
	def get_project_dependents(self, project_id: int, project_name: str, project_slug: str) -> [list, List[FileIdentifier]]:
		"""
		Get all files that depend on this project
		:param project_id:
		:param project_name:
		:param project_slug:
		:return: list of file dependents
		"""
		raise NotImplementedError

	# @abc.abstractmethod
	# def get_file_dependents(self, file: FileIdentifier) -> list[Dependant]:
	# 	raise NotImplementedError

	@abc.abstractmethod
	def get_file_dependency(self, file: FileIdentifier, project_id: int) -> Optional[FileIdentifier]:
		"""
		If the file depends on the given project returns the exact file dependency
		:param file:
		:param project_id:
		:return:
		"""
		raise NotImplementedError


class DependencyResolver(DependencyResolverInterface):

	def __init__(self, api_helper: ApiHelper, logger: logging.Logger, db_url="sqlite:///dependencies.db", **kwargs):
		self.logger: logging.Logger = logger
		self.apiHelper = api_helper
		self.bypass_distribution_restriction: bool = kwargs.get("bypass_distribution_restriction", False)
		self.use_webscraper: bool = kwargs.get("use_webscraper", False)
		self.skip_zero_downloads: bool = kwargs.get("skip_zero_downloads", False)
		self.tempFolderPath: str = kwargs.get("temp_download_folder_path", "/temp")
		self.db: Database = dataset.connect(db_url)
		self._init_db()

	def __exit__(self, exc_type, exc_val, exc_tb):
		self.db.close()

	def _init_db(self):
		db = self.db
		if not db.has_table('file'):
			table: Table = db.create_table('file')
			table.create_column('project_id', db.types.integer)
			table.create_column('file_id', db.types.integer)
			table.create_column('dependency_count', db.types.integer)

		if not db.has_table('skipped_file'):
			table: Table = db.create_table('skipped_file')
			table.create_column('project_id', db.types.integer)
			table.create_column('file_id', db.types.integer)
			table.create_column('reason', db.types.integer)
			table.create_column('timestamp', db.types.integer)
			table.create_column('url', db.types.string)

		if not db.has_table('dependency'):
			table: Table = db.create_table('dependency', primary_id=False)
			table.create_column('project_id', db.types.integer)
			table.create_column('file_id', db.types.integer)
			table.create_column('dependency_project_id', db.types.integer)
			table.create_column('dependency_file_id', db.types.integer)
			table.create_index(['project_id', 'file_id', 'dependency_project_id'])

	def is_file_depending_on_project(self, file: FileIdentifier, project_id: int) -> bool:
		if self.db['dependency'].find_one(project_id=file.project_id, file_id=file.file_id, dependency_project_id=project_id):
			return True
		return False

	def get_file_dependency(self, file: FileIdentifier, project_id: int) -> Optional[FileIdentifier]:
		result = self.db['dependency'].find_one(project_id=file.project_id, file_id=file.file_id, dependency_project_id=project_id)
		if result:
			return FileIdentifier(project_id, result['dependency_file_id'])
		return None

	def _get_mod_dependents_with_web_scraping(self, project_slug: str) -> Optional[List[int]]:
		self.logger.info(f'Using Playwright to web scrape dependents from CF...')
		ids = []
		for slug, _id in self.apiHelper.get_mod_dependents_by_web_scrapping(project_slug):
			if not _id:
				self.logger.error(f"Failed to find project id for slug <{slug}>")
				continue
			ids.append(_id)

		return ids if len(ids) > 0 else None

	def get_project_dependents(self, project_id: int, project_name: str, project_slug: str) -> [list, List[FileIdentifier]]:
		if self.use_webscraper:
			dependents_ids = self._get_mod_dependents_with_web_scraping(project_slug)
		else:
			dependents_ids = self.apiHelper.get_mod_dependents_from_mpi(project_id, project_name)

		if not dependents_ids:
			self.logger.warning("No Dependents Found")
			return [], []

		self.logger.info(f'Found {len(dependents_ids)} dependents')
		try:
			response = self.apiHelper.cf_api.get_projects(dependents_ids)
			response.raise_for_status()
			dependents = response.json()["data"]
		except requests.RequestException as error:
			self.logger.error(f"Failed to query dependents info for project id <{project_id}> -> CFCore API: {error}")
			return [], []

		resolved_files = []
		resolved_dependents = []
		for dependant in dependents:
			dependencies = self._resolve_project_dependencies(dependant)
			if len(dependencies) > 0:
				resolved_dependents.append(dependant)
				for dependency in dependencies:
					resolved_files.append(dependency)

		return resolved_dependents, resolved_files

	def _are_file_dependencies_resolved(self, file: FileIdentifier) -> bool:
		result = self.db['file'].find_one(project_id=file.project_id, file_id=file.file_id)
		if result:
			target = result['dependency_count']
			resolved = self.db['dependency'].count(project_id=file.project_id, file_id=file.file_id)
			if resolved == target:
				return True

		return False

	def _resolve_project_dependencies(self, dependant: dict) -> List[FileIdentifier]:
		self.logger.info(f'Checking dependant <{dependant["name"]}>...')

		distribution_is_restricted = not dependant["allowModDistribution"]
		if distribution_is_restricted and not self.bypass_distribution_restriction:
			self.logger.error(f"Skipping project <{dependant['name']}> because 'allowModDistribution' is set to False")
			return []

		if self.skip_zero_downloads and dependant['downloadCount'] == 0:
			self.logger.warning(f"Skipping project <{dependant['name']}> with 0 downloads -> 'skip_zero_downloads' is set to True")
			return []

		try:
			files = self.apiHelper.cf_api.get_all_project_files(dependant['id'])
		except requests.RequestException as error:
			self.logger.error(f"Failed to query project files for id <{dependant['id']}> -> CFCore API: {error}")
			return []

		self.logger.info(f'found {len(files)} files')
		resolved_dependencies = []

		self.logger.info("Checking if all dependencies are resolved...")
		for file in files:
			file_identifier = FileIdentifier(file['modId'], file['id'])

			if self._are_file_dependencies_resolved(file_identifier):
				resolved_dependencies.append(file_identifier)
				self.logger.debug(f"Skipping file <{file['fileName']}> -> dependencies already resolved")
				continue

			download_url = file['downloadUrl']
			if distribution_is_restricted and self.bypass_distribution_restriction:
				fid = str(file['id'])
				f = furl(self.apiHelper.cf_api.edge_cdn_url)
				f.path.segments = ['files', fid[0:4], fid[4:], file['fileName']]
				download_url = f.url

			if self.skip_zero_downloads and file['downloadCount'] == 0:
				self.db['skipped_file'].upsert(dict(
					project_id=file_identifier.project_id, file_id=file_identifier.file_id,
					reason=SkipReason.ZERO_DOWNLOADS.value, timestamp=int(time.time()), url=download_url
				), ['project_id', 'file_id'])
				self.logger.warning(f"Skipping file <{file['fileName']}> with 0 downloads -> 'skip_zero_downloads' is set to True")
				continue

			if not self._resolve_file_dependencies(file_identifier, file['fileName'], download_url):
				self.logger.error(f"Failed to properly resolve dependencies for <{file['fileName']}>")
				continue

			resolved_dependencies.append(file_identifier)

		return resolved_dependencies

	def remove_skipped_file(self, project_id: int, file_id: int):
		self.db['skipped_file'].delete(project_id=project_id, file_id=file_id)

	def resolve_skipped_file_dependencies(self, reason: SkipReason, timestamp: int = None):
		if timestamp:
			results = self.db['skipped_file'].find(reason=reason.value, timestamp=timestamp)
			count = self.db['skipped_file'].count(reason=reason.value, timestamp=timestamp)
		else:
			results = self.db['skipped_file'].find(reason=reason.value)
			count = self.db['skipped_file'].count(reason=reason.value)

		if results:
			self.logger.info(f"Attempting to resolve the dependencies of {count} files. This may take a while...")
			resolved = 0
			for skipped_file in results:
				fid = FileIdentifier(skipped_file['project_id'], skipped_file['file_id'])
				url = skipped_file['url']
				file_name = url.split("/")[-1]
				if not self._resolve_file_dependencies(fid, file_name, url):
					self.logger.error(f"Failed to properly resolve dependencies for <{file_name}>")
				else:
					self.db['skipped_file'].delete(project_id=fid.project_id, file_id=fid.file_id)
					resolved += 1
			self.logger.info(f"Resolved {resolved} of {count} files ({resolved / count * 100}%)")
		else:
			self.logger.info("No skipped files found.")

	def _resolve_file_dependencies(self, file: FileIdentifier, file_name: str, file_url: str, delete_temp_file=True) -> bool:
		success: bool = False

		if self._download_modpack_manifest(file, file_name, file_url):
			if self._parse_manifest_file(file):
				success = True
			else:
				self.db['skipped_file'].upsert(dict(
					project_id=file.project_id, file_id=file.file_id,
					reason=SkipReason.FILE_PARSING_ERROR.value, timestamp=int(time.time()), url=file_url
				), ['project_id', 'file_id'])
				success = False

		if delete_temp_file:
			folder_path = f"{self.tempFolderPath}/{file.project_id}_{file.file_id}"
			if os.path.exists(folder_path):
				os.remove(f"{folder_path}/manifest.json")
				os.rmdir(folder_path)

		return success

	@staticmethod
	def _resolve_cdn_url(url: str) -> str:
		try:
			response = requests.head(url, allow_redirects=True)
			response.raise_for_status()
			return response.url
		except requests.RequestException as error:
			raise GetRedirectedUrlError(f"Failed to get resultant url for <{url}> -> {error}")

	def _download_modpack_manifest(self, file: FileIdentifier, file_name: str, file_url: str) -> bool:
		try:
			# we need to get the resultant url from url redirection ourselves because RemoteZip doesn't work with url redirections
			redirected_url = self._resolve_cdn_url(file_url)
		except GetRedirectedUrlError as error:
			self.db['skipped_file'].upsert(dict(
				project_id=file.project_id, file_id=file.file_id,
				reason=SkipReason.DOWNLOAD_ERROR.value, timestamp=int(time.time()), url=file_url
			), ['project_id', 'file_id'])
			self.logger.error(f"Failed to download manifest for <{file_name}> -> {error}")
			return False

		os.makedirs(self.tempFolderPath, exist_ok=True)
		temp_folder = f"{self.tempFolderPath}/{file.project_id}_{file.file_id}"

		start_time = time.perf_counter()
		try:
			with RemoteZip(url=redirected_url) as remote:
				remote.extract('manifest.json', path=temp_folder)
				self.logger.debug(f"Downloading manifest for <{file_name}> took {time.perf_counter() - start_time} seconds")
				return True
		except RemoteIOError as error:
			self.db['skipped_file'].upsert(dict(
				project_id=file.project_id, file_id=file.file_id,
				reason=SkipReason.DOWNLOAD_ERROR.value, timestamp=int(time.time()), url=file_url
			), ['project_id', 'file_id'])
			self.logger.error(f"Failed to download manifest for <{file_name}> -> {error}")
		except IOError as error:
			self.logger.error(f"Failed to save <{temp_folder}//manifest.json> -> {error}")

		return False

	def _download_modpack(self, file: FileIdentifier, file_name: str, file_url: str, max_file_length: float) -> bool:
		try:
			response = requests.head(file_url, allow_redirects=True)
			response.raise_for_status()
			header = response.headers
			content_length = header.get('content-length', None)
			if content_length and int(content_length) > max_file_length:
				self.db['skipped_file'].upsert(dict(
					project_id=file.project_id, file_id=file.file_id,
					reason=SkipReason.DOWNLOAD_TOO_LARGE.value, timestamp=int(time.time()), url=file_url
				), ['project_id', 'file_id'])
				self.logger.error(f"Skipping download of file <{file_name}> -> File length of {int(content_length) / 1e6} MB is larger than {max_file_length / 1e6} MB")
				return False
		except requests.RequestException as error:
			self.logger.error(f"Failed to download headers for file <{file_name}> -> {error}")
			return False

		os.makedirs(self.tempFolderPath, exist_ok=True)
		file_path = f"{self.tempFolderPath}/{file.project_id}_{file.file_id}"

		start_time = time.perf_counter()
		try:
			response = requests.get(file_url, allow_redirects=True)
			response.raise_for_status()
			with open(file_path, 'wb') as f:
				f.write(response.content)
				self.logger.debug(f"Downloading file <{file_name}> took {time.perf_counter() - start_time} seconds")
				return True
		except requests.RequestException as error:
			self.db['skipped_file'].upsert(dict(
				project_id=file.project_id, file_id=file.file_id,
				reason=SkipReason.DOWNLOAD_ERROR.value, timestamp=int(time.time()), url=file_url
			), ['project_id', 'file_id'])
			self.logger.error(f"Failed to download file <{file_name}> -> {error}")
		except IOError as error:
			self.logger.error(f"Failed to save file <{file_name}> as <{file_path}> -> {error}")

		return False

	def _parse_zip_file(self, file: FileIdentifier) -> bool:
		file_path = f"{self.tempFolderPath}/{file.project_id}_{file.file_id}"
		assert os.path.exists(file_path)

		with zipfile.ZipFile(file_path) as z:
			if 'manifest.json' in z.namelist():
				return self._parse_zip_file_manifest(file, z)
			else:
				# TODO: find mod jars and get fingerprints and identify mod file with CF Core API
				self.logger.error("Missing manifest.json")
				return False

	def _parse_zip_file_manifest(self, file: FileIdentifier, zip_file: zipfile.ZipFile) -> bool:
		with zip_file.open('manifest.json') as f:
			return self._parse_manifest_data(json.load(f), file)

	def _parse_manifest_file(self, file: FileIdentifier) -> bool:
		file_path = f"{self.tempFolderPath}/{file.project_id}_{file.file_id}/manifest.json"

		if not os.path.exists(file_path):
			self.logger.error("Missing manifest.json")
			return False

		with open(file_path) as f:
			return self._parse_manifest_data(json.load(f), file)

	def _parse_manifest_data(self, data, file: FileIdentifier) -> bool:
		if "files" not in data:
			return False

		projects = data["files"]

		self.db['file'].upsert(dict(
			project_id=file.project_id, file_id=file.file_id, dependency_count=len(projects)
		), ['project_id', 'file_id'])

		for project in projects:
			self.db['dependency'].insert_ignore(dict(
				project_id=file.project_id, file_id=file.file_id,
				dependency_project_id=project["projectID"], dependency_file_id=project["fileID"]
			), ['project_id', 'file_id', 'dependency_project_id', 'dependency_file_id'])

		return True
