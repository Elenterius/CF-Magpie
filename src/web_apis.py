from typing import Optional, List

import requests
from requests import Response


class CFCoreApi:
	"""A simple helper class for the CurseForge Core API"""

	_api_key: str = None
	base_url: str = "https://api.curseforge.com"
	edge_cdn_url: str = "https://edge.forgecdn.net"
	timeout: float = None

	game_ids: dict = {
		"minecraft": 432,
	}

	def __init__(self, api_key, timeout: float = None):
		self._api_key = api_key
		self.timeout = timeout

	def _get_standard_headers(self) -> dict:
		return {
			'Accept': 'application/json',
			'x-api-key': self._api_key
		}

	def get_project(self, project_id: int) -> Response:
		return requests.get(f'{self.base_url}/v1/mods/{project_id}', headers=self._get_standard_headers(), timeout=self.timeout)

	def get_projects(self, project_ids: List[int]) -> Response:
		headers = {
			'Content-Type': 'application/json',
			'Accept': 'application/json',
			'x-api-key': self._api_key
		}
		return requests.post(f'{self.base_url}/v1/mods', headers=headers, json={"modIds": project_ids}, timeout=self.timeout)

	def find_project(self, query: dict) -> Response:
		return requests.get(f'{self.base_url}/v1/mods/search', headers=self._get_standard_headers(), params=query, timeout=self.timeout)

	def find_minecraft_project(self, query: dict) -> Response:
		query['gameId'] = self.game_ids['minecraft']
		return self.find_project(query)

	def find_minecraft_project_by_name(self, project_name: str) -> Response:
		query = {'gameId': self.game_ids['minecraft'], 'searchFilter': project_name}
		return self.find_project(query)

	def find_minecraft_project_by_slug(self, project_slug: str) -> Response:
		query = {'gameId': self.game_ids['minecraft'], 'slug': project_slug}
		return self.find_project(query)

	def find_minecraft_projects_by_slugs(self, project_slugs: List[str]):
		url = f'{self.base_url}/v1/mods/search'
		headers = self._get_standard_headers()
		query = {'gameId': self.game_ids['minecraft'], 'slug': ""}

		with requests.Session() as session:
			for slug in project_slugs:
				try:
					query["slug"] = slug
					response = session.get(url, headers=headers, params=query, timeout=self.timeout)
					response.raise_for_status()
				except requests.RequestException:
					yield slug, None
					continue

				matches = response.json()["data"]
				for match in matches:
					if match["slug"] == slug:
						yield slug, match["id"]
						break

	def get_project_desc(self, project_id: int) -> Response:
		return requests.get(f'{self.base_url}/v1/mods/{project_id}/description', headers=self._get_standard_headers(), timeout=self.timeout)

	def get_project_file(self, project_id: int, file_id: int) -> Response:
		"""
		Get one project file by file id
		"""
		return requests.get(f'{self.base_url}/v1/mods/{project_id}/files/{file_id}', headers=self._get_standard_headers(), timeout=self.timeout)

	def get_project_files(self, project_id: int, index: int, page_size: int = 50):
		"""
		Get files of the given project from a specified index/page
		"""
		if page_size > 50:
			raise ValueError(f"page_size {page_size} is larger than maximum of 50")

		if index + page_size > 10000:
			raise ValueError(f"sum of index and page_size is {index + page_size} which is larger than the limit of 10,000")

		url = f'{self.base_url}/v1/mods/{project_id}/files'
		return requests.get(url, params={"index": index, "pageSize": page_size}, headers=self._get_standard_headers(), timeout=self.timeout)

	def _get_project_files(self, session: requests.Session, project_id: int):
		url = f'{self.base_url}/v1/mods/{project_id}/files'
		curr_index = 0
		last_index = 0
		while curr_index <= last_index:
			response = session.get(url, params={"index": curr_index}, headers=self._get_standard_headers(), timeout=self.timeout)
			response.raise_for_status()
			page = response.json()
			last_index = page["pagination"]["totalCount"] - 1
			curr_index = page["pagination"]["index"] + page["pagination"]["resultCount"]
			yield page["data"]

	def get_all_project_files(self, project_id: int) -> List[dict]:
		"""
		Get all files of the given project
		"""
		with requests.Session() as session:
			all_files = []
			for files in self._get_project_files(session, project_id):
				all_files = [*all_files, *files]
			return all_files

	def get_files(self, file_ids: List[int]) -> Response:
		headers = {
			'Content-Type': 'application/json',
			'Accept': 'application/json',
			'x-api-key': self._api_key
		}
		return requests.post(f'{self.base_url}/v1/mods/files', headers=headers, json={"fileIds": file_ids}, timeout=self.timeout)


class ModpackIndexApi:
	"""A simple helper class for the Modpack Index API"""

	base_url: str = "https://www.modpackindex.com/api"

	def __init__(self):
		pass

	def _get_standard_headers(self) -> dict:
		return {
			'Accept': 'application/json'
		}

	def get_mod(self, mod_id: int) -> Response:
		return requests.get(f'{self.base_url}/v1/mod/{mod_id}', headers=self._get_standard_headers(), timeout=5)

	def find_mods(self, query: dict) -> Response:
		return requests.get(f'{self.base_url}/v1/mods', headers=self._get_standard_headers(), params=query, timeout=5)

	def find_mods_by_name(self, name: str) -> Response:
		query = {
			'name': name,
			'limit': '100', 'page': '1'
		}
		return self.find_mods(query)

	def get_mod_dependents(self, mod_id: int) -> Response:
		"""Returns the mod-packs that include this mod"""
		query = {'limit': '100', 'page': '1'}
		return requests.get(f'{self.base_url}/v1/mod/{mod_id}/modpacks', headers=self._get_standard_headers(), params=query, timeout=5)

	def get_modpack(self, modpack_id: int) -> Response:
		return requests.get(f'{self.base_url}/v1/modpack/{modpack_id}', headers=self._get_standard_headers(), timeout=5)

	def get_modpack_dependencies(self, modpack_id: int) -> Response:
		return requests.get(f'{self.base_url}/v1/modpack/{modpack_id}/mods', headers=self._get_standard_headers(), timeout=5)


class ApiHelper:
	"""A helper class that contains both apis and provides helper methods"""

	cf_api: CFCoreApi = None
	mpi_api: ModpackIndexApi = None

	def __init__(self, cf_api_key):
		self.cf_api = CFCoreApi(cf_api_key)
		self.mpi_api = ModpackIndexApi()

	def get_cf_modpack_ids(self, mpi_id) -> Optional[List[int]]:
		response = self.mpi_api.get_mod_dependents(mpi_id)  # TODO: handle pagination
		if response:
			result = response.json()
			if len(result['data']) > 0:
				modpack_ids = []
				for mod_pack in result['data']:
					modpack_ids.append(mod_pack['curse_info']['curse_id'])
				return modpack_ids
		return None

	def get_mpi_id(self, cf_id: int, cf_name: str) -> Optional[int]:
		response = self.mpi_api.find_mods_by_name(cf_name)
		if response:
			result = response.json()
			# we don't care about pagination
			# if the mod isn't in the first 100 entries, we can assume it can't be found
			if len(result['data']) > 0:
				for mod in result['data']:
					if mod['curse_info']['curse_id'] == cf_id:
						return mod['id']
		return None

	def get_mod_dependents_from_mpi(self, cf_id: int, cf_name: str) -> Optional[List[int]]:
		mpi_id = self.get_mpi_id(cf_id, cf_name)
		if mpi_id:
			return self.get_cf_modpack_ids(mpi_id)
		return None

	def get_mod_dependents_by_web_scrapping(self, cf_slug: str):
		import web_scrape_dependents as web
		slugs: List[str] = web.get_slugs_of_projects_depending_on(cf_slug)
		return self.cf_api.find_minecraft_projects_by_slugs(slugs)
