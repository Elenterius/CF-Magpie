# simple dashboard app to display some simple download stats
# built with plotly dash and tailwindcss

# Run this app with `python dashboard.py` and
# visit http://127.0.0.1:8050/ in your web browser.
import time
from datetime import datetime
from datetime import timedelta
from typing import List

import dash
import dataset
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import dcc, html, Input, Output, State
from dataset import Database
from plotly.subplots import make_subplots

import db_util


def get_project_data(db_path: str, mod_slug: str):
	db: Database = dataset.connect(db_path)

	project = db['project'].find_one(slug=mod_slug)
	if not project:
		return None

	mod_id = project['id']

	authors = db_util.get_project_authors(db, mod_id)
	authors = [author['name'] for author in authors]

	downloads_by_file: pd.DataFrame = pd.DataFrame.from_dict(db_util.get_project_downloads_by_file(db, mod_id))
	if len(downloads_by_file) > 0:
		downloads_by_file['timestamp'] = pd.to_datetime(downloads_by_file['timestamp'], unit='s')

	downloads_by_origin = get_project_downloads_by_origin(db, mod_id)
	downloads_composition: pd.DataFrame = pd.DataFrame.from_dict(db_util.get_project_downloads_by_composition(db, mod_id))

	db.close()
	return project, authors, downloads_by_file, downloads_composition, downloads_by_origin


def get_project_downloads_by_origin(db: Database, mod_id: int):
	df = pd.DataFrame.from_dict(db_util.get_project_downloads_by_origin(db, mod_id))
	if len(df) > 0:
		df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
		# df.sort_values(by=['download_count'], ascending=False, inplace=True)
	return df


def get_tracked_projects(db_path: str):
	db: Database = dataset.connect(db_path)
	projects = [p for p in db_util.get_tracked_projects_with_logo(db)]
	db.close()
	return projects


def strformat_timestamp_local(time_stamp: int):
	return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time_stamp))


def strformat_timestamp(date_time: int):
	return datetime.fromtimestamp(date_time).strftime('%Y-%m-%d %H:%M:%S')


def get_data_time_diff(timestamp: float):
	seconds = time.time() - timestamp
	seconds = timedelta(seconds=seconds)
	d = datetime(1, 1, 1) + seconds
	elapsed_time = {"years": d.year - 1, "months": d.month - 1, "days": d.day - 1, "hrs": d.hour, "min": d.minute}
	output = ""
	for key in elapsed_time.keys():
		v = elapsed_time.get(key)
		if v > 0:
			if v == 1:
				key = key.replace("s", "")
			output += str(v) + " " + key + " "

	return output


def get_percentage(a, b):
	return '%.2f' % ((a / b) * 100)


def create_project_downloads_by_file_figure(df: pd.DataFrame):
	mean = df['download_count'].mean()
	df_upper = df[df['download_count'] >= mean]
	df_lower = df[df['download_count'] < mean]

	fig = make_subplots(rows=2, cols=1)
	fig1 = px.line(
		df_upper, x="timestamp", y='download_count',
		color='file_name',
		labels={'download_count': 'Download Count', 'timestamp': 'Datetime', 'file_name': 'File'},
		hover_name='file_name', markers=True,
	)
	fig2 = px.line(
		df_lower, x="timestamp", y='download_count',
		color='file_name',
		labels={'download_count': 'Download Count', 'timestamp': 'Datetime', 'file_name': 'File'},
		hover_name='file_name', markers=True,
	)

	for d in fig1.data:
		fig.add_trace((go.Scatter(x=d['x'], y=d['y'], name=d['name'])), row=1, col=1)

	for d in fig2.data:
		fig.add_trace((go.Scatter(x=d['x'], y=d['y'], name=d['name'])), row=2, col=1)

	fig.update_layout(legend=dict(
		yanchor="middle",
		xanchor="left",
		x=1.2, y=0.5
	), legend_title_text='File')
	fig.update_layout({'plot_bgcolor': 'rgba(0, 0, 0, 0)', 'paper_bgcolor': 'rgba(0, 0, 0, 0)'}, template='plotly_dark')
	return fig


def create_downloads_by_origin_figure(df: pd.DataFrame):
	fig = px.line(
		df, x="timestamp", y='download_count',
		color='name',
		labels={'download_count': 'Download Count', 'timestamp': 'Datetime', 'name': 'Origin'},
		hover_name='name'
	)
	# fig.update_traces(textposition='inside')
	fig.update_layout({'plot_bgcolor': 'rgba(0, 0, 0, 0)', 'paper_bgcolor': 'rgba(0, 0, 0, 0)'}, template='plotly_dark')
	return fig


def create_project_downloads_figure(df: pd.Series):
	fig = px.pie(
		df,
		values=[df['dependant_download_count'], df['direct_download_count']],
		labels={'value': 'Download Count'},
		names=['Dependents', 'CurseForge Mod Page'],
		template='plotly_dark'
	)
	fig.update_layout(
		title_text=strformat_timestamp(df['timestamp']), title_x=0.5, title_y=0.075,
		legend=dict(orientation="h", yanchor="top", xanchor="center", y=1.2, x=0.5)
	)
	fig.update_layout({'plot_bgcolor': 'rgba(0, 0, 0, 0)', 'paper_bgcolor': 'rgba(0, 0, 0, 0)'})
	return fig


def create_projects_list(projects: List):
	mods = []
	modpacks = []
	for project in projects:
		li = html.Li([
			html.Img(src=project['logo'], className="w-12 h-12 rounded"),
			html.Div([
				dcc.Link([f"{project['slug']}".title()], href=f"/data/{project['slug']}", className="underline text-purple-400 hover:text-purple-600"),
				html.Div([
					"last check: ", html.Abbr([get_data_time_diff(project['date_collected'])], title=strformat_timestamp(project['date_collected'])), " ago"
				], className="text-sm")
			], className="flex flex-col"),
		], className="flex flex-row gap-2")
		if project['type'] == 'mc-mods':
			mods.append(li)
		else:
			modpacks.append(li)

	return html.Div([
		html.Div([
			html.H3(["Mods"], className="mb-2"),
			html.Ul(mods, className="flex flex-wrap gap-4")
		]),
		html.Details([
			html.Summary([f"Modpacks/Other ({len(modpacks)})"], className="focus:outline-none mb-2"),
			html.Ul(modpacks, className="flex flex-wrap gap-4 cursor-auto")
		], className="cursor-pointer")
	], className="flex flex-col gap-4 mt-2")


def create_tracked_projects_content():
	return html.Div([
		html.H2(["Tracked Projects"], className="text-xl"),
		create_projects_list(get_tracked_projects(dbUrl))
	], className="bg-gray-600 bg-opacity-50 p-3 rounded shadow-lg")


def create_error_element(error_code: int, error_msg: str):
	return html.Div([
		html.Span([str(error_code)], className="font-black text-6xl"),
		html.H1([error_msg], className="text-4xl"),
		html.Div([":("], className="mt-2 font-black text-6xl transform rotate-90 translate-x-3")
	], className="p-3 bg-gray-600 bg-opacity-50 rounded flex flex-col items-center")


def create_graph(_id, figure):
	return dcc.Graph(id=_id, config={'displaylogo': False}, figure=figure, className="mt-2 rounded theme-bg-dark shadow-lg")


def create_project_content(mod_name: str):
	try:
		project_data, authors, downloads_by_file, downloads_composition, downloads_by_origin = get_project_data(dbUrl, mod_name)
	except TypeError:
		return create_error_element(404, "Data Not Found")
	except KeyError:
		return create_error_element(500, "Internal Error")

	latest_timestamp = project_data['date_collected']

	authors = ", ".join(authors)
	project_url = f"https://www.curseforge.com/minecraft/{project_data['type']}/{project_data['slug']}"
	dropdown_options = []

	if len(downloads_composition) > 0:
		latest_download_composition = downloads_composition[downloads_composition['timestamp'] == latest_timestamp].iloc[0]
		total_downloads = latest_download_composition['total_download_count']
		direct_downloads = latest_download_composition['direct_download_count']
		dependant_download_count = latest_download_composition['dependant_download_count']
		dropdown_options = [{'label': strformat_timestamp(timestamp), 'value': timestamp} for timestamp in downloads_composition['timestamp']]
	else:
		latest_download_composition = downloads_composition
		total_downloads = downloads_by_file.groupby('timestamp').sum().sort_values(by='timestamp', ascending=False).iloc[0]['download_count']
		direct_downloads = 0
		dependant_download_count = 0

	cf_points = int(total_downloads * (100 / 5650))
	us_dollar = cf_points / 100 * 5

	try:
		composition_graph = create_graph('downloads_composition', create_project_downloads_figure(latest_download_composition))
	except KeyError:
		composition_graph = create_error_element(404, "Data Not Found")

	try:
		file_graph = create_graph('downloads_by_file', create_project_downloads_by_file_figure(downloads_by_file))
	except KeyError:
		file_graph = create_error_element(404, "Data Not Found")

	try:
		origin_graph = create_graph('downloads_origin', create_downloads_by_origin_figure(downloads_by_origin))
	except KeyError:
		origin_graph = create_error_element(404, "Data Not Found")

	return html.Div([
		html.Div([
			html.Div([
				html.Img(src=project_data["logo"], className="w-16 h-16 rounded"),
				html.Div([
					html.H1([project_data["name"]], className="text-4xl"),
					html.Div([
						"updated: ", html.Abbr([get_data_time_diff(latest_timestamp)], title=strformat_timestamp(latest_timestamp)), " ago"
					], className="text-sm")
				], className="flex flex-col")
			], className="flex flex-row gap-2"),
			html.Div([
				html.Div([
					html.H2(["Info"], className="text-xl"),
					html.Div([html.Span(["CF Id:"], className="mr-4"), html.Span([project_data["id"]])]),
					html.Div([
						html.Span(["CF Slug:"], className="mr-4"),
						html.A([
							project_data["slug"],
							html.Span(["↗"], className="group-hover:text-purple-600")
						], href=project_url, className="group text-purple-400 hover:text-purple-600 transition duration-100 ease-in")
					]),
					html.Div([html.Span(["Author:"], className="mr-4"), html.Span([authors])]),
					html.Div([html.Span(["Type:"], className="mr-4"), html.Span([project_data["type"]])]),
					html.Div([html.Span(["Created:"], className="mr-4"), html.Span([strformat_timestamp(project_data['date_created'])])]),
					html.Div([html.Span(["Updated:"], className="mr-4"), html.Span([strformat_timestamp(project_data['date_modified'])])])
				], className="bg-gray-600 bg-opacity-50 p-3 rounded shadow-lg"),
				html.Div([
					html.Div([html.H2(["Downloads"], className="text-xl")]),
					html.Span([total_downloads], className="font-black text-6xl"),
					html.Div([
						html.H3(["Composition"], className="text-lg"),
						html.Span(["Through CF Mod Page:"], className="mr-4"),
						html.Span([direct_downloads, f" ({get_percentage(direct_downloads, total_downloads)}%)"])
					], className="mt-2"),
					html.Div([
						html.Span(["Included By Dependents:"], className="mr-4"),
						html.Span([dependant_download_count, f" ({get_percentage(dependant_download_count, total_downloads)}%)"])]),
				], className="bg-gray-600 bg-opacity-50 p-3 rounded shadow-lg"),
				# html.Div([
				# 	html.H2(["Worth Estimation"], className="text-xl"),
				# 	html.Div([
				# 		cf_points, " CFP* ",
				# 		html.Small(["≈ $", html.Span(['%.2f' % us_dollar])], className="text-base"),
				# 	], className="font-black text-5xl"),
				# 	html.Small(["*Assuming 100 CF points equal 5650 downloads"], className="text-yellow-400"),
				# ], className="bg-gray-600 bg-opacity-50 p-3 rounded shadow-lg"),
			], className="flex flex-row flex-wrap items-start gap-4 mt-4")
		], className="w-full bg-gray-600 bg-opacity-50 p-3 rounded shadow-lg"),
		html.Div([
			html.Div([
				html.H2(f"Downloads by File", className="text-xl"),
				file_graph,
			], className="flex-auto w-full md:w-2/3 lg:w-3/5 xl:w-1/2"),
			html.Div([
				html.H2(f"Total Downloads Composition", className="text-xl mb-2"),
				dcc.Dropdown(
					id='timestamp-dropdown',
					options=dropdown_options,
					value=latest_timestamp,
					className="cursor-pointer"
				),
				composition_graph,
			], className="flex-auto w-full md:w-1/2 lg:w-2/5 xl:w-1/3"),
			html.Div([
				html.H2(f"Total Downloads by Origin", className="text-xl"),
				origin_graph,
			], className="flex-auto w-full md:w-2/3 lg:w-3/5 xl:w-1/2")
		], className="flex flex-row flex-wrap items-start gap-4 p-3 bg-gray-600 bg-opacity-50 rounded")
	], className="flex flex-col gap-4")


def create_sidebar_content():
	return html.Div([
		html.Div([
			html.H1("MC Mod CF Stats", className="font-black text-2xl"),
			html.Div(id='search-result', className="flex flex-col gap-2 hidden"),
		], className="flex flex-col gap-2 bg-gray-600 bg-opacity-50 p-3 rounded shadow-lg"),
		html.Nav([
			html.H1(["Nav"], className="text-xl"),
			dcc.Link(["Home"], href="/", className="text-purple-400 hover:text-purple-600"),
			# " | ",
			# dcc.Link(["Data"], href="/", className="text-purple-400 hover:text-purple-600"),
		]),
		html.Div([], id="sidebar-content"),
	], className="flex flex-col gap-4")


def create_app_layout():
	return html.Div([
		dcc.Location(id="url"),
		html.Div([
			html.Div([create_sidebar_content()], className="flex-grow md:flex-none md:flex-shrink md:w-1/3 lg:w-1/5"),
			html.Div(id="page-content", className="flex-1 overflow-y-auto"),
		], className="flex flex-col md:flex-row gap-4 p-4 pb-0")
	], className="h-full text-white")


app = dash.Dash(
	# include the whole tailwindcss build via CDN, while it has downsides (https://tailwindcss.com/docs/installation#using-tailwind-via-cdn)
	# it allows very easy styling of the dash html/dcc elements via the className parameter
	external_stylesheets=["https://unpkg.com/tailwindcss@^2/dist/tailwind.min.css"],
	suppress_callback_exceptions=True
)
app.layout = create_app_layout()


@app.callback(
	Output('downloads_composition', 'figure'),
	Input('timestamp-dropdown', 'value'),
	State("url", "pathname"),
	State('downloads_composition', 'figure')
)
def update_output(timestamp, pathname: str, prev_figure):

	if not timestamp:
		return prev_figure

	db: Database = dataset.connect(dbUrl)
	project = db['project'].find_one(slug=pathname.split("/")[-1])

	if not project:
		return prev_figure

	downloads_composition = pd.DataFrame.from_dict(db_util.get_project_downloads_by_composition(db, project['id']))
	latest_download_composition = downloads_composition[downloads_composition['timestamp'] == timestamp].iloc[0]

	db.close()
	return create_project_downloads_figure(latest_download_composition)


@app.callback(
	Output('page-content', 'children'),
	[Input("url", "pathname")]
)
def handle_page_content(pathname: str):
	if pathname == "/":
		return create_tracked_projects_content()
	elif pathname.startswith("/data/"):
		return create_project_content(pathname.replace("/data/", ""))
	return ""


@app.callback(
	Output('sidebar-content', 'children'),
	[Input("url", "pathname")]
)
def handle_sidebar_content(pathname: str):
	if pathname == "/":
		return ""
	elif pathname.startswith("/data/"):
		return create_tracked_projects_content()
	return ""


if __name__ == '__main__':
	dbUrl = "sqlite:///mod_stats.db"  # url to the database created with the DatasetSaveHandler (supports SQLite, PostgreSQL or MySQL)
	app.run_server(debug=True)
