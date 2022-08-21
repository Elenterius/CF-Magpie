from typing import List

from playwright.sync_api import sync_playwright, Page, Locator, Playwright, BrowserType, Browser, TimeoutError
from furl import furl


def get_slugs_of_projects_depending_on(project_slug: str, project_type: str = "mc-mods") -> List[str]:
	with sync_playwright() as pw:
		return _run(pw, project_slug, project_type)


def _run(playwright: Playwright, project_slug: str, project_type: str) -> List[str]:
	chromium: BrowserType = playwright.chromium  # or "firefox" or "webkit".
	browser: Browser = chromium.launch(headless=False)  # run in window mode to mitigate bot detection

	page: Page = browser.new_page()

	pagination: furl = furl(f"https://www.curseforge.com/minecraft/{project_type}/{project_slug}/relations/dependents?filter-related-dependents=6&page=1")
	page.goto(pagination.url)

	try_to_reject_all_consent(page)

	max_page_number = get_max_pagination(page)

	mod_pack_slugs = []
	for page_number in range(1, max_page_number + 1):  # TODO: open pages in several tabs in parallel
		if page_number > 1:
			pagination.args['page'] = str(page_number)
			page.goto(pagination.url)

		items: Locator = page.locator("ul.project-listing li")
		count = items.count()
		for i in range(count):
			link: str = items.nth(i).locator('a[href^="/minecraft"]').nth(0).get_attribute("href")
			if "modpacks" in link:
				mod_pack_slugs.append(link.split("/")[-1])
			# elif "mc-mods" in link:
			# 	mod_links.append(link)

	browser.close()
	return mod_pack_slugs


def get_max_pagination(page: Page):
	max_page_number = 1
	pagination_items: Locator = page.locator("div.pagination").locator("a.pagination-item")
	for i in range(pagination_items.count()):
		f = furl(pagination_items.nth(i).get_attribute("href"))
		page_number = int(f.args['page'])
		if page_number > max_page_number:
			max_page_number = page_number
	return max_page_number


def try_to_reject_all_consent(page: Page):
	try:
		consent_frame_0 = page.frame_locator('[title="SP Consent Message"]')
		consent_frame_0.locator('button[title=Options]').click()
		page.wait_for_timeout(1000)  # wait for the next consent iframe to properly load
		consent_frame_1 = page.frame_locator('[title="SP Consent Message"]').last
		consent_frame_1.locator('button[title="Reject All"]').click()
	except TimeoutError:
		pass
