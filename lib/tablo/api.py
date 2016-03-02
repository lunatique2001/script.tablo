import requests
import m3u8
import urlparse
import compat
import pytz
import traceback
import json
import discovery

DISCOVERY_URL = 'https://api.tablotv.com/assocserver/getipinfo/'

USER_AGENT = 'Tablo-Kodi/0.1'


class APIError(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args)
        self.code = kwargs.get('code')


def now():
    return compat.datetime.datetime.now(API.timezone)


def UTC():
    return pytz.timezone('UTC')


def requestHandler(f):
    def wrapper(*args, **kwargs):
        r = f(*args, **kwargs)
        if not r.ok:
            e = APIError('{0}: {1}'.format(r.status_code, '/' + r.url.split('://', 1)[-1].split('/', 1)[-1]), code=r.status_code)
            try:
                edata = r.json()
                if isinstance(edata, dict):
                    e.message = edata.get('error', edata)
                else:
                    e.message = edata
            except:
                pass
            raise e

        try:
            return r.json()
        except (ValueError, TypeError):
            return r.text

    return wrapper


def processDate(date):
        if not date:
            return None

        try:
            return API.timezone.fromutc(compat.datetime.datetime.strptime(date.rsplit('Z', 1)[0], '%Y-%m-%dT%H:%M'))
        except:
            traceback.print_exc()

        return None


class Watch(object):
    def __init__(self, path):
        try:
            data = API(path).watch.post()
            self.error = None
        except APIError, e:
            self.error = e.message.get('description', 'Unknown')

        self.base = ''
        self.url = ''
        self.width = 0
        self.height = 0

        if self.error:
            return

        self.bifSD = data.get('bif_url_sd')
        self.bifHD = data.get('bif_url_hd')
        self.expires = data.get('playlist_url')
        self.token = data.get('token')
        if 'video_details' in data:
            self.width = data['video_details']['width']
            self.height = data['video_details']['height']

        self.getPlaylistURL(data.get('playlist_url'))

    def getPlaylistURL(self, url):
        p = urlparse.urlparse(url)
        self.base = '{0}://{1}{2}'.format(p.scheme, p.netloc, p.path.rsplit('/', 1)[0])
        text = requests.get(url).text
        print repr(text)
        m = m3u8.loads(text)
        # for line in reversed(requests.get(url).text.strip().splitlines()):
        #     if line.startswith('#'):
        #         continue
        #     fromPL = line
        #     break
        # else:
        #     return

        self.url = '{0}://{1}{2}'.format(p.scheme, p.netloc, m.playlists[0].uri)

    def getSegmentedPlaylist(self):
        m = m3u8.loads(requests.get(self.url).text)
        m.base_path = self.base
        return m

    def makeSeekPlaylist(self, position):
        m = self.getSegmentedPlaylist()
        duration = m.segments[0].duration
        while duration < position:
            del m.segments[0]
            if not m.segments:
                break
            duration += m.segments[0].duration

        return m.dumps()


class Channel(object):
    def __init__(self, data):
        self.path = data['path']
        self.object_id = data['object_id']
        self.data = data

    def __getattr__(self, name):
        return self.data['channel'].get(name)


class Airing(object):
    def __init__(self, data, type_=None):
        self.path = data.get('path')
        self.scheduleData = data.get('schedule')
        self.qualifiers = data.get('qualifiers')
        self.data = data
        self.type = type_
        self._background = None
        self._thumb = None
        self._datetime = False
        self._datetimeEnd = None
        self._gridAiring = None
        self.deleted = False
        self.setType(type_)

    def setType(self, type_):
        self.type = type_

    def __getattr__(self, name):
        return self.data[self.type].get(name)

    def watch(self):
        if 'recording' in self.path:
            return Watch(self.path)
        else:
            return Watch(self.data['airing_details']['channel']['path'])

    @property
    def background(self):
        if not self._background:
            self._background = self.background_image and API.images(self.background_image['image_id']) or ''
        return self._background

    @property
    def thumb(self):
        if not self._thumb:
            self._thumb = self.thumbnail_image and API.images(self.thumbnail_image['image_id']) or ''
        return self._thumb

    @property
    def snapshot(self):
        if not self.data.get('snapshot_image'):
            return ''

        return API.images(self.data['snapshot_image']['image_id'])

    @property
    def duration(self):
        return self.data['airing_details']['duration']

    @property
    def channel(self):
        return self.data['airing_details']['channel']

    @property
    def scheduled(self):
        return self.scheduleData['state'] == 'scheduled'

    @property
    def conflicted(self):
        return self.scheduleData['state'] == 'conflict'

    def schedule(self, on=True):
        airing = API(self.path).patch(scheduled=on)
        self.scheduleData = airing.get('schedule')
        return self.scheduleData

    @property
    def datetime(self):
        if self._datetime is False:
            self._datetime = processDate(self.data['airing_details'].get('datetime'))

        return self._datetime

    @property
    def datetimeEnd(self):
        if self._datetimeEnd is None:
            if self.datetime:
                self._datetimeEnd = self.datetime + compat.datetime.timedelta(seconds=self.duration)
            else:
                self._datetimeEnd = 0

        return self._datetimeEnd

    def displayTimeStart(self):
        if not self.datetime:
            return ''

        return self.datetime.strftime('%I:%M %p').lstrip('0')

    def displayTimeEnd(self):
        if not self.datetime:
            return ''

        return self.datetimeEnd.strftime('%I:%M %p').lstrip('0')

    def displayDay(self):
        if not self.datetime:
            return ''

        return self.datetime.strftime('%A, %B {0}').format(self.datetime.day)

    def displayChannel(self):
        return '{0}-{1}'.format(
            self.data['airing_details']['channel']['channel']['major'],
            self.data['airing_details']['channel']['channel']['minor']
        )

    def secondsToEnd(self, start=None):
        start = start or now()
        return compat.timedelta_total_seconds(self.datetimeEnd - start)

    def secondsToStart(self):
        return compat.timedelta_total_seconds(self.datetime - now())

    def secondsSinceEnd(self):
        return compat.timedelta_total_seconds(now() - self.datetimeEnd)

    def airingNow(self, ref=None):
        ref = ref or now()
        return self.datetime <= ref < self.datetimeEnd

    def ended(self):
        return self.datetimeEnd < now()

    @property
    def network(self):
        return self.data['airing_details']['channel']['channel'].get('network') or ''

    # For recordings
    def delete(self):
        self.deleted = True
        return API(self.path).delete()

    @property
    def watched(self):
        return bool(self.data['user_info'].get('watched'))

    def markWatched(self, watched=True):
        recording = API(self.path).patch(watched=watched)
        self.data['user_info'] = recording.get('user_info')
        return self.data['user_info']

    @property
    def protected(self):
        return bool(self.data['user_info'].get('protected'))

    def markProtected(self, protected=True):
        recording = API(self.path).patch(protected=protected)
        self.data['user_info'] = recording.get('user_info')
        return self.data['user_info']

    @property
    def position(self):
        return self.data['user_info'].get('position')

    def setPosition(self, position=0):
        recording = API(self.path).patch(position=int(position))
        self.data['user_info'] = recording.get('user_info')
        self.data['video_details'] = recording.get('video_details')
        return self.data['user_info']


class GridAiring(Airing):
    def setType(self, type_):
        if 'series' in self.data:
            self.type = 'series'
        elif 'movie' in self.data:
            self.type = 'movie'
        elif 'sport' in self.data:
            self.type = 'sport'
        elif 'program' in self.data:
            self.type = 'program'

    @property
    def gridAiring(self):
        if not self._gridAiring:
            data = API(self.path).get()
            if 'episode' in data:
                self._gridAiring = Airing(data, 'episode')
            elif 'schedule' in data:
                self._gridAiring = Airing(data, 'schedule')
            elif 'event' in data:
                self._gridAiring = Airing(data, 'event')
            elif 'airing' in data:
                self._gridAiring = Airing(data, 'airing')

        return self._gridAiring

    @property
    def scheduled(self):
        return self.scheduleData['state'] != 'none'

    def schedule(self, on=True):
        self.scheduleData = self.gridAiring.schedule(on)
        return self.scheduleData


class Show(object):
    type = None

    def __init__(self, data):
        self.data = None
        self._thumb = ''
        self._background = ''
        self.path = data['path']
        self.scheduleRule = data.get('schedule_rule') != 'none' and data.get('schedule_rule') or None
        self.showCounts = data.get('show_counts')
        self.processData(data)

    def __getattr__(self, name):
        return self.data.get(name)

    def update(self):
        self.__init__(API(self.path).get())

    @classmethod
    def newFromData(self, data):
        if 'series' in data:
            return Series(data)
        elif 'movie' in data:
            return Movie(data)
        elif 'sport' in data:
            return Sport(data)
        elif 'program' in data:
            return Program(data)

    def processData(self, data):
        pass

    @property
    def thumb(self):
        if not self._thumb:
            try:
                self._thumb = self.data.get('thumbnail_image') and API.images(self.data['thumbnail_image']['image_id']) or ''
            except:
                print self.data['thumbnail_image']
        return self._thumb

    @property
    def background(self):
        if not self._background:
            self._background = self.data.get('background_image') and API.images(self.data['background_image']['image_id']) or ''
        return self._background

    def schedule(self, rule='none'):
        data = API(self.path).patch(schedule=rule)
        self.scheduleRule = data.get('schedule_rule') != 'none' and data.get('schedule_rule') or None

    def _airings(self):
        return API(self.path).airings.get()

    def airings(self):
        try:
            return self._airings()
        except APIError, e:
            print 'Show.airings() failed: {0}'.format(e.message)
            return []


class Series(Show):
    type = 'SERIES'
    airingType = 'episode'

    def processData(self, data):
        self.data = data['series']

    def episodes(self):
        return API(self.path).episodes.get()

    def seasons(self):
        try:
            return API(self.path).seasons.get()
        except APIError, e:
            print 'Series.seasons() failed: {0}'.format(e.message)
            return []

    def _airings(self):
        return self.episodes()


class Movie(Show):
    type = 'MOVIE'
    airingType = 'schedule'

    def processData(self, data):
        self.data = data['movie']


class Sport(Show):
    type = 'SPORT'
    airingType = 'event'

    def processData(self, data):
        self.data = data['sport']

    def events(self):
        return API(self.path).events.get()

    def _airings(self):
        return self.events()


class Program(Show):
    type = 'PROGRAM'
    airingType = 'airing'

    def processData(self, data):
        self.data = data['program']


class Endpoint(object):
    def __init__(self, segments=None):
        self.device = None
        self.segments = segments or []

    def __getattr__(self, name):
        e = Endpoint(self.segments + [name.strip('_')])
        e.device = self.device
        return e

    def __call__(self, method):
        return self.__getattr__(str(method).lstrip('/'))

    @requestHandler
    def get(self, **kwargs):
        return requests.get(
            'http://{0}/{1}'.format(self.device.address(), '/'.join(self.segments)),
            headers={'User-Agent': USER_AGENT},
            params=kwargs
        )

    @requestHandler
    def post(self, *args, **kwargs):
        return requests.post(
            'http://{0}/{1}'.format(self.device.address(), '/'.join(self.segments)),
            headers={'User-Agent': USER_AGENT},
            data=json.dumps(args and args[0] or kwargs)
        )

    @requestHandler
    def patch(self, **kwargs):
        return requests.patch(
            'http://{0}/{1}'.format(self.device.address(), '/'.join(self.segments)),
            headers={'User-Agent': USER_AGENT},
            data=json.dumps(kwargs)
        )

    @requestHandler
    def delete(self, **kwargs):
        return requests.delete(
            'http://{0}/{1}'.format(self.device.address(), '/'.join(self.segments)),
            headers={'User-Agent': USER_AGENT}
        )


class TabloApi(Endpoint):
    def __init__(self):
        Endpoint.__init__(self)
        self.device = None
        self.devices = None
        self.timezone = None
        self.serverInfo = {}

    def discover(self):
        self.devices = discovery.Devices()

    def getServerInfo(self):
        info = self.server.info.get()
        self.serverInfo = info
        timezone = info.get('timezone')
        if not timezone:
            self.timezone = pytz.UTC()

        self.timezone = pytz.timezone(timezone)

    def foundTablos(self):
        return bool(self.devices and self.devices.tablos)

    def selectDevice(self, selection):
        if isinstance(selection, int):
            self.device = self.devices.tablos[selection]
        else:
            for d in self.devices.tablos:
                if selection == d.ID:
                    self.device = d
                    break
            else:
                return False

        self.getServerInfo()

        return True

    def deviceSelected(self):
        return bool(self.device)

    def images(self, ID):
        return 'http://{0}/images/{1}'.format(self.device.address(), ID)


API = TabloApi()
