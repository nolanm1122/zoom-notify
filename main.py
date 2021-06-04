import json
import re
import traceback
from datetime import datetime
from json.decoder import JSONDecodeError

from dateutil import parser
import os

import requests
from canvasapi import Canvas
from pushbullet import Pushbullet
from tqdm import tqdm

from settings import *
from lxml.html import fromstring

SCID_PATTERN = r'scid:\"([a-zA-Z0-9]+)\"'
XSRF_PATTERN = r'"X-XSRF-TOKEN", value:\"([a-zA-Z0-9-]+)'
PROXIES = {'http': 'http://localhost:8080', 'https': 'http://localhost:8080'}


def localize(dt) -> datetime:
    local = dt.replace(tzinfo=pytz.utc).astimezone(TZ)
    return TZ.normalize(local)


def get_zoom_tab(tabs):
    for tab in tabs:
        if 'zoom' in tab.label.lower():
            return tab
    return None


def day_letter(dt: datetime) -> str:
    return dt.strftime("%A")[0]


def get_zoom_form(tree):
    hidden_inputs = tree.cssselect(
        'form[action="https://applications.zoom.us/lti/rich"] input')
    form = {}
    for hidden_input in hidden_inputs:
        form[hidden_input.get('name')] = hidden_input.get('value')
    return form


def notify_custom(f_name, pb, now: datetime):
    with open(f_name) as f:
        try:
            j = json.loads(f.read())
        except JSONDecodeError:
            return
        for meeting in j:
            if day_letter(now) not in meeting['days']:
                continue
            begin_hour = int(meeting['begin_time'].split(':')[0])
            begin_minute = int(meeting['begin_time'].split(':')[1])
            begin = now.replace(hour=begin_hour, minute=begin_minute)
            if now > begin:
                continue
            if abs((begin - now).total_seconds()) <= 60 * NOTIFY_WITHIN_MINUTES:
                pb.push_link(meeting['name'], meeting['url'], body=meeting['description'])


def main():
    if not os.path.exists(CACHE_DIR):
        os.mkdir(CACHE_DIR)
    pb = Pushbullet(PB_TOKEN)
    try:
        canvas = Canvas('https://uiowa.instructure.com/', CANVAS_API_KEY)
        courses = canvas.get_courses(enrollment_state='active')
        canvas_session = canvas._Canvas__requester._session
        canvas_session.headers['Authorization'] = 'Bearer ' + CANVAS_API_KEY
        zoom_session = requests.session()
        notify_custom('./meetings.json', pb, datetime.now(tz=TZ))
        for course in tqdm(courses):
            tabs = course.get_tabs()
            zoom_tab = get_zoom_tab(tabs)
            if not zoom_tab:
                continue
            r = canvas_session.get(zoom_tab.url)
            url = r.json()['url']
            r = canvas_session.get(url)
            tree = fromstring(r.text)
            form = get_zoom_form(tree)
            r = zoom_session.post('https://applications.zoom.us/lti/rich', data=form)
            scid = re.findall(SCID_PATTERN, r.text)[0]
            xsrf = re.findall(XSRF_PATTERN, r.text)[0]
            url = 'https://applications.zoom.us/api/v1/lti/rich/meeting/upComing/COURSE/all'
            params = {'page': '1',
                      'total': '0',
                      'storage_timezone': 'America/Chicago',
                      'client_timezone': 'America/Chicago',
                      'lti_scid': scid}
            r = zoom_session.get(url, params=params, headers={'X-XSRF-TOKEN': xsrf})
            for meeting in r.json()['result']['list']:
                now = datetime.now(tz=TZ)
                start_time = meeting.get('startTime')
                if not start_time:
                    continue
                start = localize(parser.parse(start_time))
                if now > start:
                    continue
                if abs((start - now).total_seconds()) <= 60 * NOTIFY_WITHIN_MINUTES:
                    pb.push_link(meeting['topic'] + ' - ' + meeting['startTimeForList'], meeting['joinUrl'], body=course.name)
    except Exception:
        print(traceback.format_exc())
        # pb.push_note('Zoom-Notifier', traceback.format_exc())


if __name__ == '__main__':
    main()
