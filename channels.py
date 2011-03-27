import time
import datetime
import simplejson
from channel import BaseChannel, ChannelException,ChannelMetaClass, STATUS_BAD, STATUS_GOOD, STATUS_UGLY
from utils import *
import xbmcplugin
class ThePlatformBaseChannel(BaseChannel):
    is_abstract = True
    base_url = None
    PID = None
    category_cache_timeout = 60 # value is in seconds. so 5 minutes.

    def get_categories_json(self):
        return self.base_url + 'getCategoryList?PID=%s'%(self.PID) + \
            '&field=ID&field=depth&field=title&field=description&field=hasReleases&field=fullTitle&field=thumbnailURL&field=hasChildren'

    def get_releases_json(self):
        return self.base_url + 'getReleaseList?PID=%s'%(self.PID) + \
            '&field=title&field=PID&field=ID&field=description&field=categoryIDs&field=thumbnailURL&field=URL&field=airdate&field=length&field=bitrate' + \
            '&sortField=airdate&sortDescending=true&startIndex=1&endIndex=100'



    def parse_callback(self, body):
        logging.debug('parse_callback body %s:' % body)
        return simplejson.loads(body)


    def get_cache_key(self):
        return self.short_name
    
    def get_cached_categories(self, parent_id):
        
        categories = None

        fpath = os.path.join(self.plugin.get_cache_dir(), 'canada.on.demand.%s.categories.cache' % (self.get_cache_key(),))
        try:
            if os.path.exists(fpath):
                data = simplejson.load(open(fpath))
                if data['cached_at'] + self.category_cache_timeout >= time.time():
                    logging.debug("using cached Categories")
                    categories = data['categories']
        except:
            logging.debug("no cached Categories path")

        if not categories:
            logging.debug('http-retrieving categories')
            url = self.get_categories_json(parent_id)
            logging.debug('get_cached_categories(p_id=%s) url=%s'%(parent_id, url))
        
            categories = self.parse_callback(get_page(url).read())['items']
            if self.category_cache_timeout > 0:
                fpath = os.path.join(self.plugin.get_cache_dir(), 'canada.on.demand.%s.categories.cache' % (self.short_name,))
                fh = open(fpath, 'w')
                simplejson.dump({'cached_at': time.time(), 'categories': categories}, fh)
                fh.close()

        return categories

    
    def get_categories(self, parent_id=None):

        categories = self.get_cached_categories(parent_id)

        #needs to be defined by sub-class:
        #  - CBC does an actual drill-down on parentId
        #  - Canwest uses string-matching on the fullTitle field
        categories = self.get_child_categories(categories, parent_id)
            
        cats = []
        for c in categories:
            #logging.debug(c)
            data = {}
            data.update(self.args)
            data.update({
                'entry_id': c['ID'],
                'Thumb': c['thumbnailURL'],
                'Title': c['title'],
                'Plot': c['description'],
                'action': 'browse',
                'force_cache_update': False,
            })
            
            #cbc-only, so check if key is present on other providers (Canwest)
            if 'customData' in c:
                for dict in c['customData']:
                    if dict['value']:
                        #if dict['value'] == '(not specified)':
                            #dict['value'] = "''"
                        #if dict['value'] != '':
                        data.update({dict['title']: dict['value']},) #urlquoteval(dict['value'])
                
            cats.append(data)
            
        logging.debug("get_categories cats=%s"%cats)
        return cats


    def get_releases(self, parameter): #category_id for Canwest, a customData dict for CBC 
        logging.debug('get_releases (parameter=%s)'%parameter)
        
        url = self.get_releases_json(parameter) #has a %s in it--  Canwest:a real cat_id, CBC: the customTags, 
        logging.debug('get_releases url=%s'%url)
        
        data = self.parse_callback(get_page(url).read())
        make_playlists = self.plugin.get_setting('make_playlists') == 'true'
        max_bitrate = int(self.plugin.get_setting('max_bitrate'))
        
        rels = []
        for item in data['items']:
            item['bitrate'] = int(item['bitrate'])/1024
            if (not rels) or (rels[-1]['Title'] != item['title']):
                
                action = 'browse_episode'
                if make_playlists:
                    action = 'play_episode'
                
                rels.append({
                    'Thumb': item['thumbnailURL'],
                    'Title': item['title'],
                    'Plot': item['description'],
                    'entry_id': item['ID'],
                    'remote_url': item['URL'],
                    'remote_PID': item['PID'],
                    'channel': self.args['channel'],
                    'action': action,
                    'bitrate': item['bitrate'],
                })

            else:
                if item['bitrate'] <= max_bitrate and item['bitrate'] > rels[-1]['bitrate']:
                    rels.pop()
                    action = 'browse_episode'
                    if make_playlists:
                        action = 'play_episode'
                    
                    rels.append({
                        'Thumb': item['thumbnailURL'],
                        'Title': item['title'],
                        'Plot': item['description'],
                        'entry_id': item['ID'],
                        'remote_url': item['URL'],
                        'remote_PID': item['PID'],
                        'channel': self.args['channel'],
                        'action': action,
                        'bitrate': item['bitrate'],
                    })
                    
                
        return rels


    def action_root(self):
        logging.debug('ThePlatformBaseChannel::action_root')
        parent_id = self.args['entry_id'] # this should be None from @classmethod
        if parent_id == 'None':
            parent_id = None
        categories = self.get_categories(parent_id)# and root=true
        for cat in categories:
            self.plugin.add_list_item(cat)
        self.plugin.end_list()


    def action_browse(self):
        """
        Handles the majority of the navigation.

        """
        parent_id = self.args['entry_id']

        categories = self.get_categories(parent_id)
        logging.debug("Got %s Categories: %s" % (len(categories), "\n".join(repr(c) for c in categories)))
        releases = self.get_releases(self.args)
        logging.debug("Got %s Releases: %s" % (len(releases), "\n".join(repr(r) for r in releases)))

        for cat in categories:
            self.plugin.add_list_item(cat)
        for rel in releases:
            self.plugin.add_list_item(rel)
        self.plugin.end_list()


    def get_episode_list_data(self, remote_pid):
        url = 'http://release.theplatform.com/content.select?&pid=%s&format=SMIL&mbr=true' % (remote_pid,)
        soup = get_soup(url)
        logging.debug("SOUP: %s" % (soup,))
        results = []

        for i, ref in enumerate(soup.findAll('ref')):
            base_url = ''
            playpath = None

            if ref['src'].startswith('rtmp://'): #all other channels type of SMIL
            #the meta base="http:// is actually the prefix to an adserver
                try:
                    base_url, playpath = decode_htmlentities(ref['src']).split('<break>', 1) #<break>
                except ValueError:
                    base_url = decode_htmlentities(ref['src'])
                    playpath = None
                logging.debug('all other channels type of SMIL  base_url=%s  playpath=%s'%(base_url, playpath))
            else:
                if soup.meta['base'].startswith('rtmp://'): #CBC type of SMIL
                    base_url = decode_htmlentities(soup.meta['base'])
                    playpath = ref['src']
                    logging.debug('CBC type of SMIL  base_url=%s  playpath=%s'%(base_url, playpath))
                else:
                    continue

            qs = None
            try:
                base_url, qs = base_url.split("?",1)
            except ValueError:
                base_url = base_url

            logging.debug({'base_url': base_url, 'playpath': playpath, 'qs': qs, })

            clip_url = base_url
            if playpath:
                clip_url += playpath
            if qs:
                clip_url += "?" + qs

            data = {}
            data.update(self.args)
            data['Title'] = self.args['Title']# + " clip %s" % (i+1,)
            data['clip_url'] = clip_url
            data['action'] = 'play'
            results.append(data)
        return results
    
    def action_play_episode(self):
        import xbmc
        playlist = xbmc.PlayList(1)
        playlist.clear() 
        for data in self.get_episode_list_data(self.args['remote_PID']):
            url = self.plugin.get_url(data)
            item = self.plugin.add_list_item(data, is_folder=False, return_only=True)
            playlist.add(url, item)
        xbmc.Player().play(playlist)
        xbmc.executebuiltin('XBMC.ActivateWindow(fullscreenvideo)')

        
    def action_browse_episode(self):
        for item in self.get_episode_list_data(self.args['remote_PID']):
            self.plugin.add_list_item(item, is_folder=False)
        self.plugin.end_list()


    def action_play(self):
        parse = URLParser(swf_url=self.swf_url)
        self.plugin.set_stream_url(parse(self.args['clip_url']))


    @classmethod
    def get_channel_entry_info(self):
        """
        This method is responsible for returning the info 
        used to generate the Channel listitem at the plugin's
        root level.

        """
        return {
            'Title': self.long_name,
            'Thumb': self.icon_path,
            'action': 'root',
            'entry_id': None,
            'channel': self.short_name,
            'force_cache_update': True,
        }


class CTVBaseChannel(BaseChannel):
    status = STATUS_BAD
    is_abstract = True
    root_url = 'VideoLibraryWithFrame.aspx'
    default_action = 'root'
    
    def action_root(self):
        url = self.base_url + self.root_url
        soup = get_soup(url)
        ul = soup.find('div', {'id': 'Level1'}).find('ul')
        for li in ul.findAll('li'):
            data = {}
            data.update(self.args)
            data['Title'] = decode_htmlentities(li.a['title'])
            data['action'] = 'browse_show'
            data['show_id'] = li.a['id']
            self.plugin.add_list_item(data)
        self.plugin.end_list()
        
    def action_browse_season(self):
        url = "http://esi.ctv.ca/datafeed/pubsetservice.aspx?sid=" + self.args['season_id']
        page = get_page(url).read()
        soup = BeautifulStoneSoup(page)
        for ep in soup.overdrive.gateway.contents:
            logging.debug("ASDF: %s" % (ep.contents,))
            if not ep.playlist.contents:
                continue
            data = {}
            data.update(self.args)
            data['Title'] = ep.meta.headline.contents[0].strip()
            data['Plot'] = ep.meta.subhead.contents[0].strip()
            m,d,y = ep['pubdate'].split("/")
            data['Date'] = "%s.%s.%s" % (d,m,y)
            try:
                data['Thumb'] = ep.meta.image.contents[0].strip()
            except:
                pass
            
            data['videocount'] = ep['videocount']
            vc = int(ep['videocount'])
            if vc == 1:
                action = 'play_episode'
            elif vc <= int(self.plugin.get_setting('max_playlist_size')) \
                 and self.plugin.get_setting("make_playlists") == "true":
                action = 'play_episode'
            else:
                action = 'browse_episode'
            data['action'] = action
            data['episode_id'] = ep['id']
            self.plugin.add_list_item(data, is_folder=vc != 1)
        self.plugin.end_list('episodes', [xbmcplugin.SORT_METHOD_DATE, xbmcplugin.SORT_METHOD_LABEL])
        
    def action_play_episode(self):
        import xbmc
        vidcount = self.args.get('videocount')
        if vidcount:
            vidcount = int(vidcount)
        
        if vidcount  and vidcount == 1:
            data = list(self.iter_clip_list())[0]
            logging.debug(data)
            url = self.clipid_to_stream_url(data['clip_id'])
            return self.plugin.set_stream_url(url, data)
        else:
            playlist = xbmc.PlayList(1)
            playlist.clear()
            for clipdata in self.iter_clip_list():
                url = self.plugin.get_url(clipdata)
                li = self.plugin.add_list_item(clipdata, is_folder=False, return_only=True)
                ok = playlist.add(url, li)
                logging.debug("CLIPDATA: %s, %s, %s, %s" % (clipdata, url, li, ok))
            
            time.sleep(1)
            logging.debug("CLIPDATA: %s" % (playlist,))
            xbmc.Player().play(playlist)
            xbmc.executebuiltin('XBMC.ActivateWindow(fullscreenvideo)')
            self.plugin.end_list()

    def iter_clip_list(self):
        url = "http://esi.ctv.ca/datafeed/content.aspx?cid=" + self.args['episode_id']
        page = get_page(url).read()
        soup = BeautifulStoneSoup(page)
        logging.debug(soup)
        plot = soup.find('content').meta.subhead.contents[0].strip()
                             
        for el in soup.find('playlist').findAll('element'):
            data = {}
            data.update(self.args)
            data['action'] = 'play_clip'
            data['Title'] = el.title.contents[0].strip()
            data['Plot'] = plot
            data['clip_id'] = el['id']
            yield data
            
    def action_browse_episode(self):
        logging.debug("ID: %s" % (self.args['episode_id'],))
        for data in self.iter_clip_list():
            self.plugin.add_list_item(data, is_folder=False)
        self.plugin.end_list()
        
        
    def action_browse_show(self):
        url = self.base_url + 'VideoLibraryContents.aspx?GetChildOnly=true&PanelID=2&ShowID=%s' % (self.args['show_id'],)
        soup = get_soup(url)
        div = soup.find('div',{'id': re.compile('^Level\d$')})
        levelclass = [c for c in re.split(r"\s+", div['class']) if c.startswith("Level")][0]
        levelclass = int(levelclass[5:])
        if levelclass == 4:
            # Sites like TSN Always return level4 after the top level
            for li in soup.findAll('li'):
                a = li.find('dl', {"class": "Item"}).dt.a
                data = {}
                data.update(self.args)
                data.update(parse_bad_json(a['onclick'][45:-16]))
                data['action'] = 'play_clip'
                data['clip_id'] = data['ClipId']
                self.plugin.add_list_item(data, is_folder=False)
            self.plugin.end_list()
        
        else:
            for li in soup.find('ul').findAll('li'):
                a = li.find('a')
                is_folder = True
                data = {}
                data.update(self.args)
                if "Interface.GetChildPanel('Season'" in a['onclick']:
                    data['action'] = 'browse_season'
                    data['season_id'] = a['id']
                elif "Interface.GetChildPanel('Episode'" in a['onclick']:
                    data['action'] = 'browse_episode'
                    if self.plugin.get_setting("make_playlists") == "true":
                        data['action'] = 'play_episode'
                    data['episode_id'] = a['id'][8:]
                data['Title'] = decode_htmlentities(a['title'])
                self.plugin.add_list_item(data)
            self.plugin.end_list()
        
    def clipid_to_stream_url(self, clipid):
        rurl = "http://esi.ctv.ca/datafeed/urlgenjs.aspx?vid=%s" % (clipid)
        parse = URLParser(swf_url=self.swf_url, force_rtmp=not self.plugin.get_setting("awesome_librtmp") == "true")        
        url = parse(get_page(rurl).read().strip()[17:].split("'",1)[0])
        return url
    
    def action_play_clip(self):
        url = self.clipid_to_stream_url(self.args['clip_id'])
        logging.debug("Playing Stream: %s" % (url,))
        self.plugin.set_stream_url(url)
        


class CanwestBaseChannel(ThePlatformBaseChannel):
    is_abstract = True
    base_url = 'http://feeds.theplatform.com/ps/JSON/PortalService/2.2/'
    PID = None
    root_depth = 1

    def get_categories_json(self,arg=None):
        return ThePlatformBaseChannel.get_categories_json(self) # + '&query=ParentIDs|%s'%arg

    def get_releases_json(self,arg='0'):
        return ThePlatformBaseChannel.get_releases_json(self) + '&query=CategoryIDs|%s'% (self.args['entry_id'],)

    def children_with_releases(self, categorylist, cat):
        
        if cat['fullTitle'] == '':
            prefix = ''
        else:
            prefix = cat['fullTitle'] + "/"
        
        children = [c for c in categorylist \
                    if c['depth'] == cat['depth'] + 1 \
                    and c['fullTitle'].startswith(prefix) \
                    and (c['hasReleases'] or self.children_with_releases(categorylist, c))]
        return children
            
        
    def get_child_categories(self, categorylist, parent_id):
        
        show_empty = self.plugin.get_setting('show_empty_cat') == 'true'
        if parent_id is None:
            if self.root_depth > 0:
                cat = [c for c in categorylist if c['depth'] == self.root_depth - 1][0]
            else:
                cat = {'depth': -1, 'fullTitle': ''}
        else:
            logging.debug("ParentID: %s [%s]" % (parent_id, type(parent_id)))
            cat = [c for c in categorylist if c['ID'] == int(parent_id)][0]
        
        if cat['fullTitle'] == '':
            prefix = ''
        else:
            prefix = cat['fullTitle'] + "/"
        
        if show_empty:
            categories = [c for c in categorylist if c['depth'] == cat['depth'] + 1 \
                          and c['fullTitle'].startswith(prefix)]
            
        else:
            categories = self.children_with_releases(categorylist, cat)

        return categories


    #override ThePlatFormbase so ?querystring isn't included in playpath 
    #this could be temp-only, actually. paypath doesn't seem to care about extra parameters
    def action_play(self):
        parse = URLParser(swf_url=self.swf_url, playpath_qs=False)
        self.plugin.set_stream_url(parse(self.args['clip_url']))



class GlobalTV(CanwestBaseChannel):
    short_name = 'global'
    long_name = 'Global TV'
    PID = 'W_qa_mi18Zxv8T8yFwmc8FIOolo_tp_g'
    #swf_url = 'http://www.globaltv.com/video/swf/flvPlayer.swf'

    
    def get_categories_json(self,arg=None):
        url = CanwestBaseChannel.get_categories_json(self,arg) + '&query=CustomText|PlayerTag|z/Global%20Video%20Centre' #urlencode
        logging.debug('get_categories_json: %s'%url)
        return url

    def get_releases_json(self,arg='0'):
        url = '%s' % CanwestBaseChannel.get_releases_json(self,arg)
        logging.debug('get_releases_json: %s'%url)
        return url

class GlobalNews(CanwestBaseChannel):
    short_name = 'globalnews'
    long_name = 'Global News'
    PID = 'M3FYkz1jcJIVtzmoB4e_ZQfqBdpZSFNM'
    local_channels = [
        ('Global News','z/Global%20News%20Player%20-%20Main'),
        ('Global National','z/Global%20Player%20-%20The%20National%20VC'),
        ('BC', 'z/Global%20BC%20Player%20-%20Video%20Center'),
        ('Calgary', 'z/Global%20CGY%20Player%20-%20Video%20Center'),
        ('Edmonton', 'z/Global%20EDM%20Player%20-%20Video%20Center'),
        ('Lethbridge', 'z/Global%20LTH%20Player%20-%20Video%20Center'),
        ('Maritimes', 'z/Global%20MAR%20Player%20-%20Video%20Center'),
        ('Montreal', 'z/Global%20QC%20Player%20-%20Video%20Center'),
        ('Regina', 'z/Global%20REG%20Player%20-%20Video%20Center'),
        ('Saskatoon', 'z/Global%20SAS%20Player%20-%20Video%20Center'),
        ('Toronto', 'z/Global%20ON%20Player%20-%20Video%20Center'),
        ('Winnipeg', 'z/Global%20WIN%20Player%20-%20Video%20Center'),
    ]
    
    def get_cache_key(self):
        return "%s-%s" % (self.short_name, self.args.get('local_channel',''))
    
    def action_browse(self):
        self.PlayerTag = dict(self.local_channels)[self.args['local_channel']]
        
        if self.args['entry_id'] is None:
            return CanwestBaseChannel.action_root(self)
        return CanwestBaseChannel.action_browse(self)
        
    
    def action_root(self):
        for channel, ptag in self.local_channels:
            self.plugin.add_list_item({
                'Title': channel, 
                'action': 'browse',
                'channel': self.short_name, 
                'entry_id': None,
                'local_channel': channel
            })
        self.plugin.end_list()
    
    def get_categories_json(self, arg):
        return CanwestBaseChannel.get_categories_json(self, arg) + '&query=CustomText|PlayerTag|' + self.PlayerTag
    
    
class CTVLocalNews(CTVBaseChannel):
    short_name = 'ctvlocal'
    long_name = 'CTV Local News'
    default_action = 'root'
    
    local_channels = [
        ('British Columbia', 'ctvbc.ctv.ca'),
        ('Calgary', 'calgary.ctv.ca'),
        ('Edmonton', 'edmonton.ctv.ca'),
        ('Montreal', 'montreal.ctv.ca'),
        ('Northern Ontario', 'northernontario.ctv.ca'),
        ('Ottawa', 'ottawa.ctv.ca'),
        ('Regina', 'regina.ctv.ca'),
        ('Saskatoon', 'saskatoon.ctv.ca'),
        ('Southwestern Ontario', 'swo.ctv.ca'),
        ('Toronto', 'toronto.ctv.ca'),
        ('Winnipeg', 'winnipeg.ctv.ca'),
    ]

        
    def action_root(self):
        for channel, domain in self.local_channels:
            self.plugin.add_list_item({
                'Title': channel, 
                'action': 'browse',
                'channel': self.short_name, 
                'entry_id': None,
                'local_channel': channel,
                'remote_url': domain,

                'Thumb': self.args['Thumb'],
            })
        self.plugin.end_list()

        
    def action_browse(self):
        soup = get_soup("http://%s/" % (self.args['remote_url'],))
        for script in soup.findAll('script'):
            try:
                txt = script.contents[0].strip()
            except:
                continue
            
            if txt.startswith("VideoPlaying["):
                txt = txt.split("{",1)[1].rsplit("}")[0]
                
                data = {}
                data.update(self.args)
                data.update(parse_javascript_object(txt))
                data.update({
                    'action': 'play_clip',
                    'remote_url': data['ClipId'],
                    'clip_id': data['ClipId']
                })
                self.plugin.add_list_item(data, is_folder=False)
        self.plugin.end_list()
        
class HistoryTV(CanwestBaseChannel):
    short_name = 'history'
    long_name = 'History TV'
    PID = 'IX_AH1EK64oFyEbbwbGHX2Y_2A_ca8pk'
    swf_url = 'http://www.history.ca/video/cwp/swf/flvPlayer.swf'

    def get_categories_json(self,arg):
        url = CanwestBaseChannel.get_categories_json(self,arg) + '&query=CustomText|PlayerTag|z/History%20Player%20-%20Video%20Center' #urlencode
        logging.debug('get_categories_json: %s'%url)
        return url


class FoodNetwork(CanwestBaseChannel):
    short_name = 'foodnet'
    long_name = 'The Food Network'
    PID = '6yC6lGVHaVA8oWSm1F9PaIYc9tOTzDqY'
    #swf_url = 'http://webdata.globaltv.com/global/canwestPlayer/swf/4.1/flvPlayer.swf'

    def get_categories_json(self,arg):
        url = CanwestBaseChannel.get_categories_json(self,arg) + '&query=CustomText|PlayerTag|z/FOODNET%20Player%20-%20Video%20Centre' #urlencode
        logging.debug('get_categories_json: %s'%url)
        return url


class HGTV(CanwestBaseChannel):
    short_name = 'hgtv'
    long_name = 'HGTV.ca'
    PID = 'HmHUZlCuIXO_ymAAPiwCpTCNZ3iIF1EG'
    #swf_url = 'http://www.hgtv.ca/includes/cwp/swf/flvPlayer.swf'

    def get_categories_json(self,arg):
        url = CanwestBaseChannel.get_categories_json(self,arg) + '&query=CustomText|PlayerTag|z/HGTV%20Player%20-%20Video%20Center' #urlencode
        logging.debug('get_categories_json: %s'%url)
        return url



class Showcase(CanwestBaseChannel):
    short_name = 'showcase'
    long_name = 'Showcase'
    PID = 'sx9rVurvXUY4nOXBoB2_AdD1BionOoPy'
    #swf_url = 'http://www.showcase.ca/video/swf/flvPlayer.swf'
    root_depth = 2
    def get_categories_json(self,arg):
        url = CanwestBaseChannel.get_categories_json(self,arg) + '&query=CustomText|PlayerTag|z/Showcase%20Video%20Centre' #urlencode
        logging.debug('get_categories_json: %s'%url)
        return url

    


class SliceTV(CanwestBaseChannel):
    short_name = 'slice'
    long_name = 'Slice TV'
    PID = 'EJZUqE_dB8XeUUgiJBDE37WER48uEQCY'
    #swf_url = 'http://www.slice.ca/includes/cwp/swf/flvPlayer.swf'

    def get_categories_json(self,arg):
        url = CanwestBaseChannel.get_categories_json(self,arg) + '&query=CustomText|PlayerTag|z/Slice%20Player%20-%20New%20Video%20Center' #urlencode
        logging.debug('get_categories_json: %s'%url)
        return url


class TVTropolis(CanwestBaseChannel):
    short_name = 'tvtropolis'
    long_name = 'TVtropolis'
    PID = '3i9zvO0c6HSlP7Fz848a0DvzBM0jUWcC'
    #swf_url = 'http://www.tvtropolis.com/swf/cwp/flvPlayer.swf'

    def get_categories_json(self, arg=None):
        url = CanwestBaseChannel.get_categories_json(self) + '&query=CustomText|PlayerTag|z/TVTropolis%20Player%20-%20Video%20Center' #urlencode
        logging.debug('get_categories_json: %s'%url)
        return url


class diyNet(CanwestBaseChannel):
    short_name = 'diynet'
    long_name = 'The DIY Network'
    PID = 'FgLJftQA35gBSx3kKPM46ZVvhP6JxTYt'
    #swf_url = 'http://www.diy.ca/Includes/cwp/swf/flvPlayer.swf'

    def get_categories_json(self,arg):
        url = CanwestBaseChannel.get_categories_json(self,arg) + '&query=CustomText|PlayerTag|z/DIY%20Network%20-%20Video%20Centre' #urlencode
        logging.debug('get_categories_json: %s'%url)
        return url



class YTV(CanwestBaseChannel):
    short_name = 'ytv'
    long_name = 'YTV'
    PID = 't4r_81mEo8zCyfYh_AKeHJxmZleq26Vx'
    swf_url = 'http://www.ytv.com/PDK/swf/flvPlayer.swf'
    root_depth = 0
    
    def get_categories_json(self,arg):
        url = CanwestBaseChannel.get_categories_json(self,arg) + '&field=parentID&query=IncludeParents' #urlencode
        logging.debug('get_categories_json: %s'%url)
        return url


class TreehouseTV(CanwestBaseChannel):
    short_name = 'treehouse'
    long_name = 'Treehouse TV'
    PID = '6FTFywmxdSd_HKMYKQGFwsAf8rkcdn9R'
    swf_url = 'http://mediaparent.treehousetv.com/swf/flvPlayer.swf'
    root_depth = 0



class CBCChannel(ThePlatformBaseChannel):
    #is_abstract = True
    PID = "_DyE_l_gC9yXF9BvDQ4XNfcCVLS4PQij"
    base_url = 'http://cbc.feeds.theplatform.com/ps/JSON/PortalService/2.2/'
    status = STATUS_UGLY
    short_name = 'cbc'
    long_name = 'CBC'
    category_cache_timeout = 0 # can't cache for CBC, need to drill-down each time

    #this holds an initial value for CBC only to get the top-level categories;
    #it is overwritten in action_root
    in_root = False
    category_json = '&query=ParentIDs|'
   
    def get_categories_json(self, arg):
        logging.debug('get_categories_json arg=%s, categ_json=%s'%(arg, self.category_json))
        url = ThePlatformBaseChannel.get_categories_json(self) + \
            '&customField=Account&customField=Show&customField=SeasonNumber&customField=AudioVideo&customField=ClipType&customField=LiveOnDemand'
        if arg or self.in_root:
            url += self.category_json
        if arg:
            url += arg
        return url

    #arg is CBC's customfield array from getReleases query
    def get_releases_json(self,arg):
        url = ThePlatformBaseChannel.get_releases_json(self)
        logging.warn("RELURL: %s" % (url,))
        if 'Account' in arg:
            url += '&query=ContentCustomText|Account|%s' % urlquoteval(arg['Account'])
        if 'Show' in arg:
            url += '&query=ContentCustomText|Show|%s' % urlquoteval(arg['Show'])
        if 'SeasonNumber' in arg:
            url += '&query=ContentCustomText|SeasonNumber|%s' % urlquoteval(arg['SeasonNumber'])
        if 'AudioVideo' in arg:
            url += '&query=ContentCustomText|AudioVideo|%s' % urlquoteval(arg['AudioVideo'])
        if 'ClipType' in arg:
            url += '&query=ContentCustomText|ClipType|%s' % urlquoteval(arg['ClipType'])
        if 'LiveOnDemand' in arg:
            url += '&query=ContentCustomText|LiveOnDemand|%s' % urlquoteval(arg['LiveOnDemand'])


        #url += '&query=CategoryIDs|%s'%arg['entry_id']
        logging.debug('get_releases_json: %s'%url)
        return url
        
    def get_child_categories(self, categorylist, parent_id):
        if parent_id is None:
            categories = [c for c in categorylist \
                          #if c['depth'] == 1 or c['depth'] == 0
                          if c['depth'] == 0
                          and (
                              self.plugin.get_setting('show_empty_cat') == True
                              or (c['hasReleases'] or c['hasChildren'])
                          )]
        else:
            #do nothing with parent_id in CBC's case
            categories = categorylist
        return categories

    def action_root(self):
        logging.debug('CBCChannel::action_root')
        
        #all CBC sections = ['Shows,Sports,News,Kids,Radio']
        self.category_json = ''
        self.in_root = True #just for annoying old CBC
        self.category_json = '&query=FullTitles|Shows,Sports,News,Kids,Radio'
        categories = self.get_categories(None)
        
        for cat in categories:
            cat.update({'Title': 'CBC %s'%cat['Title']})
            self.plugin.add_list_item(cat)
        self.plugin.end_list()

        #restore ParentIDs query for sub-categories
        self.category_json = '&query=ParentIDs|'
        self.in_root = False
        logging.debug('setting categ_json=%s'%self.category_json)


class CTV(CTVBaseChannel):
    short_name = 'ctv'
    long_name = 'CTV'
    base_url = 'http://watch.ctv.ca/AJAX/'
    swf_url = 'http://watch.ctv.ca/Flash/player.swf?themeURL=http://watch.ctv.ca/themes/CTV/player/theme.aspx'


class TSN(CTVBaseChannel):
    short_name = 'tsn'
    long_name = 'The Sports Network'
    base_url = 'http://watch.tsn.ca/AJAX/'    
    swf_url = 'http://watch.tsn.ca/Flash/player.swf?themeURL=http://watch.ctv.ca/themes/TSN/player/theme.aspx'


class CTVNews(CTVBaseChannel):    
    base_url = 'http://watch.ctv.ca/news/AJAX/'
    short_name = 'ctvnews'
    long_name = 'CTV News'
    swf_url = 'http://watch.ctv.ca/news/Flash/player.swf?themeURL=http://watch.ctv.ca/news/themes/CTVNews/player/theme.aspx'


class Discovery(CTVBaseChannel):
    short_name = 'discovery'
    base_url = 'http://watch.discoverychannel.ca/AJAX/'
    long_name = 'Discovery'
    swf_url = 'http://watch.discoverychannel.ca/Flash/player.swf?themeURL=http://watch.discoverychannel.ca/themes/Discoverynew/player/theme.aspx'




class ComedyNetwork(CTVBaseChannel):
    status = STATUS_UGLY
    short_name = 'comedynetwork'
    base_url = 'http://watch.thecomedynetwork.ca/AJAX/'
    long_name = 'The Comedy Network'
    swf_url = 'http://watch.thecomedynetwork.ca/Flash/player.swf?themeURL=http://watch.thecomedynetwork.ca/themes/Comedy/player/theme.aspx'



class Space(CTVBaseChannel):
    short_name = 'space'
    long_name = "Space" 
    base_url = "http://watch.spacecast.com/AJAX/"
    swf_url = "http://watch.spacecast.com/Flash/player.swf?themeURL=http://watch.spacecast.com/themes/Space/player/theme.aspx"

class MuchMusic(CTVBaseChannel):
    status = STATUS_BAD
    short_name = 'muchmusic'
    long_name = 'Much Music'
    base_url = 'http://watch.muchmusic.com/AJAX/'
    swf_url = 'http://watch.muchmusic.com/Flash/player.swf?themeURL=http://watch.muchmusic.com/themes/MuchMusic/player/theme.aspx'



class Bravo(CTVBaseChannel):
    short_name = 'bravo'
    long_name = "Bravo!"
    base_url = 'http://watch.bravo.ca/AJAX/'
    swf_url = 'http://watch.bravo.ca/Flash/player.swf?themeURL=http://watch.bravo.ca/themes/CTV/player/theme.aspx'


class BNN(CTVBaseChannel):
    base_url = 'http://watch.bnn.ca/AJAX/'
    long_name = 'Business News Network'
    short_name = 'bnn'
    swf_url = 'http://watch.bnn.ca/news/Flash/player.swf?themeURL=http://watch.bnn.ca/themes/BusinessNews/player/theme.aspx'



class Fashion(CTVBaseChannel):
    short_name = 'fashion'
    base_url = 'http://watch.fashiontelevision.com/AJAX/'
    long_name = 'Fashion Television'
    swf_url = 'http://watch.fashiontelevision.com/Flash/player.swf?themeURL=http://watch.fashiontelevision.com/themes/FashionTelevision/player/theme.aspx'


class BravoFact(CTVBaseChannel):
    long_name = 'Bravo Fact'
    short_name = 'bravofact'
    base_url = 'http://watch.bravofact.com/AJAX/'
    swf_url = 'http://watch.bravofact.com/Flash/player.swf?themeURL=http://watch.bravofact.com/themes/BravoFact/player/theme.aspx'
  
class TouTV(ThePlatformBaseChannel):
    long_name = 'Tou.TV'
    short_name='toutv'
    base_url = 'http://www.tou.tv/repertoire/'
    swf_url = 'http://static.tou.tv/lib/ThePlatform/4.2.9c/swf/flvPlayer.swf'
    default_action = 'root'
    
    categories = [
            ("animation","Animation"),
            ("entrevues-varietes", "Entrevues et varietes"),
            ("films-documentaires","Films et documentaires"),
            ("magazines-affaires-publiques", "Magazines et affaires publiques"),
            ("series-teleromans", "Series et teleromans"),
            ("spectacles-evenements", "Spectacles et evenements"),
            ("webteles",u"Webteles"),
    ]
  
    def action_browse_episode(self):
        url = self.args['remote_url']
        soup = get_soup(url)
        scripts = soup.findAll('script')
        
        epinfo_tag = [s for s in scripts if s.contents and s.contents[0].strip().startswith("// Get IP address and episode ID")][0]
        self.args['remote_PID'] = re.search(r"episodeId = '([^']+)'", epinfo_tag.contents[0].strip()).groups()[0]
        return ThePlatformBaseChannel.action_browse_episode(self)
        
    def action_play_episode(self):
        url = self.args['remote_url']
        soup = get_soup(url)
        scripts = soup.findAll('script')
        
        epinfo_tag = [s for s in scripts if s.contents and s.contents[0].strip().startswith("// Get IP address and episode ID")][0]
        self.args['remote_PID'] = re.search(r"episodeId = '([^']+)'", epinfo_tag.contents[0].strip()).groups()[0]
        return ThePlatformBaseChannel.action_play_episode(self)
        

    def action_play(self):
        parse = URLParser(swf_url=self.swf_url)
        self.plugin.set_stream_url(parse(self.args['clip_url']))        
            
    def action_browse_series(self):
        url = self.args['remote_url']
        soup = get_soup(url)
        for row in soup.findAll('div', {'class': 'blocepisodeemission'}):
            
            data = {}
            data.update(self.args)
            images = row.findAll('img')
            if len(images) == 2:
                image = images[1]
            else:
                image = images[0]
                
            title = decode_htmlentities(row.find('a', {'class': 'episode'}).b.contents[0],)[:-1]
            
            try:
                seasonp = [p for p in row.findAll('p') if 'class' in dict(p.attrs)][0]
                season = seasonp.contents[0].strip()
                title = season + ": " + title
            except:
                pass
                
            try:
                plotp = [p for p in row.findAll('p') if 'class' not in dict(p.attrs)][0]
                plot = plotp.contents[0].strip()
            except:
                plot = '(failed to fetch plot)'
                
                
            action = 'browse_episode'
            if self.plugin.get_setting("make_playlists") == "true":
                action = "play_episode"
                
            data.update({
                'action': action,
                'remote_url': 'http://tou.tv' + row.find('a')['href'],
                'Title': title,
                'Thumb': image['src'],
                'Plot': plot
            })
            self.plugin.add_list_item(data)
        self.plugin.end_list()
            
    def action_browse_category(self):
        cat = dict(self.categories)[self.args['category']]
        logging.debug("CAT: %s" % (cat,))
        url = self.base_url + self.args['category'] + "/"
        soup = get_soup(url)
        logging.debug(url)
        for a in soup.findAll('a', {'class': re.compile(r'bloc_contenu.*')}):
            data = {}
            data.update(self.args)
            data.update({
                'action': 'browse_series',
                'remote_url': 'http://tou.tv' + a['href'],
                'Title': a.find('h1').contents[0],
            })
            
            self.plugin.add_list_item(data)
        self.plugin.end_list()
        
    def action_root(self):
        
        for cat in self.categories:
            data = {}
            data.update(self.args)
            data.update({
                'channel': 'toutv',
                'action': 'browse_category',
                'category': cat[0],
                'Title': cat[1],
            })
            
            self.plugin.add_list_item(data)
        self.plugin.end_list()
        
        
class CPAC(BaseChannel):
    short_name = 'cpac'
    long_name = "CPAC"
    default_action = 'root'
    base_url = "http://www.cpac.ca/forms/"
    icon_path = 'cpac.jpg'
    
    def action_play_video(self):
        remote_url = self.base_url + self.args['remote_url']
        soup = get_soup(remote_url)
        obj = soup.find("object", {'id': "MPlayer2"})
        vidurl = obj.find('param', {'name': 'url'})['value']
        asx = get_soup(vidurl)
        entries = asx.findAll('entry')
        if len(entries) > 1:
            entries = entries[1:]
        
        if len(entries) > 1:
            self.plugin.get_dialog().ok("Error", "Too Many Entries to play")
            return None
        
        url = entries[0].ref['href']
        return self.plugin.set_stream_url(url)
        
    def action_list_episodes(self):
        soup = get_soup(self.base_url + self.args['remote_url'])
        for li in soup.find('div', {'id': 'video_scroll'}).findAll('div', {'class': 'list_item'}):
            links = li.findAll('a')
            ep_title = links[0].contents[0]
            show_title = links[1].contents[0]
            date_str = links[2].contents[0]
            self.plugin.add_list_item({
                'action': 'play_video',
                'channel': 'cpac',
                'remote_url': links[0]['href'],
                'Title': "%s (%s)" % (ep_title, date_str),
            }, is_folder=False)
            
            
        self.plugin.end_list()

    def action_list_shows(self):
        soup = get_soup(self.base_url)
        select = soup.find('select', {"name": 'proglinks'})
        for show in select.findAll('option')[1:]:
            data = {}
            data.update(self.args)
            data['action'] = 'list_episodes'
            data['remote_url'] = show['value'].split("|",1)[1]
            data['Title'] = show.contents[0]
            self.plugin.add_list_item(data)
        self.plugin.end_list()
        
    def action_latest_videos(self):
        url = self.base_url + "index.asp?dsp=template&act=view3&section_id=860&template_id=860&hl=e"
        soup = get_soup(url)
        for li in soup.find('div', {'id': 'video_scroll'}).findAll('div', {'class': 'list_item'}):
            links = li.findAll('a')
            ep_title = links[0].contents[0]
            show_title = links[1].contents[0]
            date_str = links[2].contents[0]
            logging.debug("VID: %s, %s" % (ep_title, show_title))
            self.plugin.add_list_item({
                'action': 'play_video',
                'channel': 'cpac',
                'remote_url': links[0]['href'],
                'Title': "%s - %s (%s)" % (show_title, ep_title, date_str),
            }, is_folder=False)
            
            
        self.plugin.end_list()
        
    def action_root(self):
        self.plugin.add_list_item({
            'action': 'latest_videos',
            'Title': 'Latest Videos',
            'channel': 'cpac',
        })
        self.plugin.add_list_item({
            'action': 'list_shows',
            'Title': 'All Shows',
            'channel': 'cpac',
        })
        self.plugin.end_list()
        
class Family(BaseChannel):
    status = STATUS_BAD
    short_name = 'family'
    long_name = 'Family.ca'
    base_url = 'http://www.family.ca'
    default_action = 'root'
    
    class FamilyURLParser(URLParser):
        def get_base_url(self):
            print self.data
            url = "%(scheme)s://%(netloc)s/%(app)s" % self.data
            if self.data['querystring']:
                url += "?%(querystring)s" % self.data
            return url
        
        def get_url_params(self):
            params = super(Family.FamilyURLParser, self).get_url_params()
            params.append(('pageUrl', 'http://www.family.ca/video/#video=%s' % (726,)))
            return params
    def action_play_video(self):
        qs = urldecode(get_page(self.base_url + "/video/scripts/loadToken.php").read().strip()[1:])['uri']
        filename = self.args['filename']
        url = "rtmpe://cp107996.edgefcs.net/ondemand/videos/family/%s?%s" % (filename, qs)
        parser = Family.FamilyURLParser(swf_url="http://www.family.ca/video/player.swf", playpath_qs=False)
        url = parser(url)
        self.plugin.set_stream_url(url)
        
    def action_browse_category(self):
        results = simplejson.load(get_page(self.base_url + "/video/scripts/loadGroupVideos.php?groupID=%s" % (self.args['id'],)))
        for vid in results['videosbygroup']:
            data = {}
            data.update(self.args)

            if vid['thumb']:
                thumb = self.base_url + "/video/images/thumbnails/%s" % (vid['thumb'],)
            else:
                thumb = ''
            data['Title'] = vid['title']
            data['Plot'] = vid['description']
            data['Thumb'] = thumb
            data['filename'] = vid['filename']
            data['action'] = 'play_video'
            self.plugin.add_list_item(data, is_folder=False)
        self.plugin.end_list()
        
    def action_root(self):
        soup = get_soup(self.base_url + "/video/")
        logging.debug(soup)
        div = soup.find('div', {'id': 'categoryList'})
        data = {}
        data.update(self.args)
        data['action'] = 'browse_featured'
        data['Title'] = 'Featured Videos'
        self.plugin.add_list_item(data)
        
        for a in div.findAll('a')[3:]:
            data = {}
            data.update(self.args)
            data['Title'] = decode_htmlentities(a.contents[0].strip())
            data['action'] = 'browse_category'
            data['id'] = a['href'].split("(",1)[1].split(",")[0]
            self.plugin.add_list_item(data)
        self.plugin.end_list()