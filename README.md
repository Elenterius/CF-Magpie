# Magpie
Get more **Download Stats** for **Minecraft Mods** hosted on **CurseForge**.

When you host a mod on CurseForge (CF) you will eventually realize that the download stats provided by CF
only show you the total download count.

The new CF dashboard does show now the daily & monthly download count, but you still won't
know how many downloads are from modpacks or which specific version of a modpack includes your mod.
Or which version of your mod still receives downloads.

## How it Works
The scripts in this repository utilize the `CFCore API` and `ModpackIndex API` or a `WebScraper powered by Playwright` in order to figure out which modpacks include your mod. 
Then the manifest of each version of a modpack is checked to determine which modpack file depends on your mod.

Note: The download composition is determined by all of your public available mod files 
(archived files can't be queried using the CFCore api) which may skew the resulting stats.

## How to get the Data
> You need a CurseForge Core **API Key**

You can get the API key from https://core.curseforge.com/. 
Just login with a Google account and name your organisation with an arbitrary name, and you will automatically
get an API Key that can query mod and file data from the **CFCore API**.

### Example
```Python
import mod_data_collector
from dependency_resolver import DependencyResolver
from save_handlers import DatasetSaveHandler
from web_apis import ApiHelper

...

cf_api_key = "YOUR_CF_CORE_API_KEY"
mod_id = 492939  # Project Id (you can find it on the cf mod page) or use the CFCoreAPI to search for the mod by name

api_helper = ApiHelper(cf_api_key)

with DependencyResolver(api_helper, logger) as dependency_resolver:
  # save handler implementation of your choice
  with DatasetSaveHandler("sqlite:///mod_stats.db", int(time.time())) as save_handler:
    mod_data_collector.collect_data(logger, save_handler, dependency_resolver, api_helper, mod_id)
```

## Structure of Database created by DatasetSaveHandler
https://github.com/Elenterius/DS-MM-CF/blob/main/db_schema.md

## dashboard_app.py
If you used the `DatasetSaveHandler` to store the data in a sqlite db you can run `python dashboard_app.py` for a simple dashboard web app (built with plotly dash and tailwindcss)
which displays some rudimentary download stats.
