import logging
import time

import dataset
import requests
from dataset import Table

import mod_data_collector
from dependency_resolver import DependencyResolver, SkipReason
from save_handlers import DatasetSaveHandler
from web_apis import ApiHelper


def create_logger():
	# configure logger
	console_handler = logging.StreamHandler()
	console_handler.setLevel(logging.DEBUG)
	console_handler.setFormatter(logging.Formatter('[%(asctime)s][%(name)s][%(levelname)s]:: %(message)s'))
	logger = logging.getLogger("Mod")
	logger.setLevel(logging.DEBUG)
	logger.addHandler(console_handler)
	return logger


def main(cf_core_api_key: str, mod_id: int, force: bool = False):
	logger = create_logger()

	timestamp = int(time.time())

	api_helper = ApiHelper(cf_core_api_key)
	with DependencyResolver(api_helper, logger.getChild("DependencyResolver")) as dependency_resolver:  # bypass_distribution_restriction=True, use_webscraper=True
		# SaveHandler implementation of your choice
		with DatasetSaveHandler("sqlite:///mod_stats.db", timestamp) as save_handler:
			save_handler.db.begin()
			if mod_data_collector.collect_data(logger.getChild("DataCollector"), save_handler, dependency_resolver, api_helper, mod_id, force=force):
				logger.info("committing changes to db...")
				save_handler.db.commit()
			else:
				logger.info("rollback db changes...")
				save_handler.db.rollback()


def resolve_skipped_dependencies(cf_core_api_key: str):
	logger = create_logger()
	api_helper = ApiHelper(cf_core_api_key)
	with DependencyResolver(api_helper, logger.getChild("DependencyResolver")) as dependency_resolver:
		dependency_resolver.resolve_skipped_file_dependencies(SkipReason.DOWNLOAD_TOO_LARGE)


def resolve_dependency_relations(cf_core_api_key: str, mod_id: int):
	logger = create_logger()
	api_helper = ApiHelper(cf_core_api_key)
	with DependencyResolver(api_helper, logger.getChild("DependencyResolver")) as dependency_resolver:
		try:
			response = api_helper.cf_api.get_project(mod_id)
			response.raise_for_status()
			project = response.json()["data"]
		except requests.RequestException as error:
			logger.error(f"Failed to query project info for id <{mod_id}> -> CFCore API: {error}")
			return

		dependents, files = dependency_resolver.get_project_dependents(project['id'], project['name'], project['slug'])


def dumb_db_info(db_url: str):
	db = dataset.connect(db_url)
	print("dumping database info...")
	print("---")
	tables = db.tables
	for table_id in tables:
		table: Table = db[table_id]
		print("Table:", table_id, "\n  Columns:", table.columns, "\n  Rows:", len(table))
	print("---")
	db.close()


if __name__ == '__main__':
	CF_CORE_API_KEY = "YOUR_CF_CORE_API_KEY"
	main(CF_CORE_API_KEY, 492939, False)

	# resolve_skipped_dependencies(CF_CORE_API_KEY)
	# dumb_db_info("sqlite:///dependencies.db")
	# dumb_db_info("sqlite:///mod_stats.db")

	# db = dataset.connect("sqlite:///dependencies.db")
	# uniqueIds = set()
	# for row in db['dependency'].find(dependency_project_id=401247):  # look for Pehkui
	# 	uniqueIds.add(row['project_id'])
	# db.close()
	#
	# db = dataset.connect("sqlite:///mod_stats.db")
	# for row in db['project'].find(dependency_project_id=uniqueIds):
	# 	print(row['name'])
	# db.close()
	#
	# api_helper = ApiHelper(CF_CORE_API_KEY)
	# try:
	# 	response = api_helper.cf_api.get_mod_file(mod_id=398244, file_id=3488006)
	# 	response.raise_for_status()
	# 	project = response.json()["data"]
	# 	print(project)
	# except requests.RequestException as error:
	# 	print(f"Failed to query projects by ids -> CFCore API: {error}")

	# try:
	# 	response = api_helper.cf_api.get_mods(list(uniqueIds))
	# 	response.raise_for_status()
	# 	projects = response.json()["data"]
	# 	for project in projects:
	# 		print(project['name'])
	# except requests.RequestException as error:
	# 	print(f"Failed to query projects by ids -> CFCore API: {error}")

	# time.sleep(0.1)
	# print(">>> Dumping skipped files >>>")
	# db = dataset.connect("sqlite:///dependencies.db")
	# for row in db['skipped_file']:
	# 	print("projectId:", row['project_id'], "reason:", SkipReason(row['reason']).name, "url:", row['url'])
	# print(f"...found {len(db['skipped_file'])} skipped files")

	# db.close()
