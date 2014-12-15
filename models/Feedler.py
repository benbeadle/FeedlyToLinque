from google.appengine.ext import ndb
from utils.consts import *
import logging, json, re, webapp2, secrets
from google.appengine.api import memcache

import utils.query as Query

#A Feedler is a Feedly user who has logged in
class Feedler(ndb.Model):
    #Store their email address so they can be notified of errors
    email = ndb.StringProperty('em', default="", indexed=False)
    first_name = ndb.StringProperty('fn', default="", indexed=False)

    #The access/refresh token to authorize Feedly
    access_token = ndb.StringProperty('at', required=True, indexed=False)
    refresh_token = ndb.StringProperty('rt', required=True, indexed=False)
    expires = ndb.DateTimeProperty('ex', required=True, indexed=False)

    #The Linque API key to send articles to the Feedler's Linque account
    #Found under Settings in Linque.
    linque_api_key = ndb.StringProperty('lak', default="", indexed=False)
    
    #Stores if they have a pro account or not
    is_pro = ndb.BooleanProperty('ip', required=True, indexed=False)

    receive_updates = ndb.BooleanProperty('ru', default=True, indexed=False)

    #Store when they first authorized Feedly
    created = ndb.DateTimeProperty('cr', auto_now_add=True, indexed=False)

    #TODO: Add counters for how many Triggers have been created and how many articles Linqued today / total

    #The ID corresponds to their Feedly ID
    @property
    def id(self):
        return self.key.id()

    #Quick access to the Feedly API
    @property
    def feedly_api(self):
        return FeedlyAPI(self)

    #Make sure the access token and Linque API Key aren't empty
    @property
    def can_run_triggers(self):
        return (self.access_token != "" and self.linque_api_key != "")

    #Return the Triggers the Feedler has created
    def all_triggers(self):
        return Query.feedler_triggers(self.key)

    #Check if any data from authentication has changed since their
    #last authentication
    def has_changed(self, auth_data, expires):
        return not (self.access_token == auth_data["access_token"]
            and self.refresh_token == auth_data["refresh_token"]
            and self.is_pro == (auth_data["plan"] == "pro")
            and self.expires == expires)

    #Mark the account as not authorized (we lost access)
    def set_not_authed(self):
        self.access_token = ""
        self.put()

        Emailer.need_to_authorize(self)

    #
    #   These are a bunch of helper methods to get resource IDs
    #
    def _get_resource_id(self, resource, label):
        return "user/%s/%s/%s" % (self.id, resource, label)

    def get_category(self, label):
        return self._get_resource_id("category", label)
    def get_tag(self, label):
        return self._get_resource_id("tag", label)
    def get_topic(self, label):
        return self._get_resource_id("topic", label)

    def get_global_must(self):
        return self.get_category("global.must")
    def get_global_uncategorized(self):
        return self.get_category("global.uncategorized")
    def get_global_recently_read(self):
        return self.get_category("global.read")
    def get_global_all(self):
        return self.get_category("global.all")
    def get_global_saved(self):
        return self.get_tag("global.saved")
    #
    #   End resouce ID helper methods
    #

    #Check if the Feedler needs to update their settings
    #if they are missing data
    def force_settings(self):
        return (self.first_name == ""
            or self.email == ""
            or self.linque_api_key == "")

    #A simple metho to get a list of all the Global Resource IDs
    def all_globals(self):
        ress = []
        ress.append({"label":"All Articles","id":self.get_global_all()})
        ress.append({"label":"Must Haves","id":self.get_global_must()})
        ress.append({"label":"Uncategorized Articles","id":self.get_global_uncategorized()})
        ress.append({"label":"Recently Read Articles","id":self.get_global_recently_read()})
        ress.append({"label":"Saved For Later Articles","id":self.get_global_saved()})
        return ress

    #
    #   The below methods get a list of resources (categories/tags/etc) from a Feedler's account
    #

    #Grab all of the user's resources of a certain id, saving to memcache before returning
    @ndb.tasklet
    def _all_resource_async(self, resource_id, use_mem=True):

        #Check if the response was saved to memcache before
        #calling the API again
        mem_id = "%s/%s" % (self.id, resource_id)
        if use_mem:
            vals = memcache.get(mem_id, None)
            if vals is not None:
                raise ndb.Return(vals)

        #If not, then call the API
        datas = yield self.feedly_api.get_endpoint_async("/v3/%s" % resource_id)

        #Convert the list to JSON
        json_data = []
        for data in datas:
            id = data["id"]
            label = data["label"] if "label" in data else (data["title"] if "title" in data else id)

            json_data.append({
                "id": id,
                "label": label
            })

        #Save to memcache for 5 minutes before returning the result
        memcache.set(mem_id, json_data, time=300)

        raise ndb.Return(json_data)

    def all_subscriptions_async(self, use_mem=True):
        return self._all_resource_async("subscriptions", use_mem)
    def all_subscriptions(self, use_mem=True):
        return self.all_subscriptions_async(use_mem).get_result()

    @ndb.tasklet
    def all_tags_async(self, use_mem=True):
        tags = yield self._all_resource_async("tags", use_mem)
        tags = [t for t in tags if not t["label"].endswith("global.saved")]
        raise ndb.Return(tags)
    def all_tags(self, use_mem=True):
        return self.all_tags_async(use_mem).get_result()

    def all_categories_async(self, use_mem=True):
        return self._all_resource_async("categories", use_mem)
    def all_categories(self, use_mem=True):
        return self.all_categories_async(use_mem).get_result()

    @ndb.tasklet
    def all_topics_async(self, use_mem=True):
        topics = yield self._all_resource_async("topics", use_mem)
        topics.append({
            "id": "topic/global.popular",
            "label": "Most Popular 50,000 Sources in Feedly"
        })
        raise ndb.Return(topics)
    def all_topics(self, use_mem=True):
        return self.all_topics_async(use_mem).get_result()
    
    #
    #   End resource ID getter methods from the Feedly API
    #


    #Linque an article to the Feedler's Linque account asynchronously
    #Optionally linqueing a device directly intead of the account
    def linque_it_to_me_async(self, url, title, device_name=""):
        from google.appengine.api import urlfetch
        import urllib

        data = {
            "api_key": self.linque_api_key,
            "url": url.encode('utf-8').strip(),
            "description": title.encode('utf-8').strip()
        }

        if device_name != "":
            data["device_name"] = device_name

        data = urllib.urlencode(data)
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}

        #TODO: Check if the response told us there was an invalid API key
        #and if so email them to let them know they need to update their Linque API Key
        rpc = urlfetch.create_rpc()
        urlfetch.make_fetch_call(rpc, secrets.LINQUE_SEND_URL, payload=data, method="post", headers=headers)
        return rpc

    #Save the refresh data if the access token was invalid and a call to get
    #a new one was required
    def save_refresh_data(self, refresh_data):
        import datetime

        expires = datetime.datetime.now() + datetime.timedelta(0, refresh_data["expires_in"])
        access_token = refresh_data["access_token"]
        plan = refresh_data["plan"]

        self.access_token = access_token
        self.expires = expires
        self.is_pro = (plan == "pro")

        self.put()

    #Signs in the User
    def log_in(self):
        me = Crypt.en(self.id, secrets.FEEDLER_LOGIN_KEY)
        session_set("me", me, True)

    #Either gets the Feedler or creates and returns depending
    #if the user has authenticated before
    @classmethod
    def get_or_create(self, auth_data):
        import datetime

        feedler_id = auth_data["id"]
        expires = datetime.datetime.now() + datetime.timedelta(0, auth_data["expires_in"])

        feedler = Feedler.get_by_id(feedler_id)

        #If it hasn't changed, then just return it
        if feedler is not None and not feedler.has_changed(auth_data, expires):
            return feedler

        access_token = auth_data["access_token"]

        #If the account wasn't found, then go ahead and create it
        #We also need to get the user's profile to get name and email
        if feedler is None:
            feedler = Feedler(id=feedler_id)

            fc = get_feedly_client()
            profile = fc.get_user_profile(access_token=access_token)
            
            #Save their name and email
            if "givenName" in profile:
                feedler.first_name = profile["givenName"]
            if "email" in profile:
                feedler.email = profile["email"]

        #Update all their information in case of data change
        feedler.access_token = access_token
        feedler.refresh_token = auth_data["refresh_token"]
        feedler.is_pro = (auth_data["plan"] == "pro")
        feedler.expires = expires

        feedler.put()

        return feedler


    #Logs the Feedler out of the app
    @classmethod
    def log_out(self):
        session_delete("me")

    #Get's the logged in Feedler (if there is one)
    @classmethod
    def logged_in_feedler(cls):

        me = session_get("me")

        if me is None:
            return None

        me = Crypt.de(me, secrets.FEEDLER_LOGIN_KEY)

        if me == "":
            return None

        #If there is a session, but it doesn't contain a valid owner
        #Terminate the session (signout)
        o = Feedler.get_by_id(me)
        if o is None:
            Feedler.log_out()
        return o


class FeedlerHandler(webapp2.RequestHandler):
    feedler = None
    feedly_api = None

    @property
    def feedler_key(self):
        if self.feedler is None:
            return None
        return self.feedler.key

    def render_template(self, view_filename, params={}):
        params["feedler"] = self.feedler
        render_template(self, view_filename, params)

    def render_trigger(self, trigger_cls_id, editing, params={}):
        from google.appengine.ext.webapp import template
        
        trigger_path = HTML_FILE.format("triggers/%s" % trigger_cls_id)
        trigger_render = template.render(trigger_path, params)

        params["trigger_fields"] = trigger_render
        
        view_filename = "trigger_%s" % ("edit" if editing else "new")
        self.render_template(view_filename, params)

    def on_page(self, page):
        return self.request.path == ("/%s" % page)

    def redirect_home(self):
        self.redirect(self.request.get("r", "/app"), abort=True)

    # this is needed for webapp2 sessions to work
    def dispatch(self):

        feedler = Feedler.logged_in_feedler()
        self.feedler = feedler

        #If they aren't logged in, then authenticate with Feedly
        #Also, force authentication if requested in the URL
        if feedler is None or self.request.get("force", "") == "auth":
            feedly = get_feedly_client()
            code_url = feedly.get_code_url(FEEDLY_REDIRECT_URI)
            self.redirect(code_url, abort=True)
        else:
            on_settings = self.on_page("app/settings")
            #If their name or email wasn't found, then they need to enter it in
            if feedler.force_settings() and not on_settings:
                import urllib

                ret_path = self.request.path
                query = self.request.query_string
                if query != "" and query != "?":
                    ret_path += "?" + query
                ret_path = urllib.quote(ret_path)

                settings_url = "/app/settings"
                if ret_path != "/app":
                    settings_url += "?r=" + ret_path

                self.redirect(settings_url, abort=True)

            self.feedly_api = feedler.feedly_api

        # Dispatch the request.
        webapp2.RequestHandler.dispatch(self)

class FeedlyAPI(object):
    def __init__(self, feedler):
        self.feedler = feedler
        self.fc = get_feedly_client()

    def _invalid_token_response(self, response):
        return "errorCode" in response and response["errorCode"] == 401

    def _get_call(self, fcmethod, *arg):
        at = self.feedler.access_token
        return fcmethod(at, *arg)

    def _make_call(self, fcmethod, *arg):
        response = self._get_call(fcmethod, *arg)

        #If the auth token is invalid, then try to get a new one
        if self._invalid_token_response(response):
            rt = self.feedler.refresh_token
            refresh_resp = self.fc.refresh_access_token(rt)

            #If we couldn't get a new token, then just return the
            #original response
            if "errorCode" in refresh_resp:
                self.feedler.set_not_authed()
                return response

            #Save the updated access token
            self.feedler.save_refresh_data(refresh_resp)

            #Try the original request with the new token
            response = self._get_call(fcmethod, *arg)

            #Not really sure if this will happen, but just in case!
            if self._invalid_token_response(response):
                self.feedler.set_not_authed()

        return response

    def get_endpoint(self, endpoint, params={}):
        return self.fc.get_endpoint(self.feedler.access_token, endpoint, params)

    def get_endpoint_async(self, endpoint, params={}):
        return self.fc.get_endpoint_async(self.feedler.access_token, endpoint, params)
    
    def get_user_subscriptions(self):
        '''return list of user subscriptions'''
        return self._make_call(self.fc.get_user_subscriptions)
    
    def search_stream(self, stream_id, query, newer_than, unread_only=False, fields="", embedded="", enagement="", locale=""):
        #/v3/search/contents
        params = {
            "query": query,
            "streamId": stream_id,
            "newerThan": newer_than
        }
        
        #Add optional filters to the params
        if fields != "":
            params["fields"] = fields
        if embedded != "":
            params["embedded"] = embedded
        if enagement != "":
            params["enagement"] = enagement
        if locale != "":
            params["locale"] = locale

        endpoint = "/v3/search/contents"

        items = []
        keep_going = True
        continuation = ""
        api_calls = 0

        #This is for continuation
        #Keep grabbing more items until all are grabbed
        while keep_going and api_calls <= 20:

            params["continuation"] = continuation

            response = self._make_call(self.fc.get_endpoint, endpoint, params)
            api_calls += 1

            if "items" in response:
                items.extend(response["items"])

            #Do we need to keep going to get more results?
            if "continuation" in response:
                continuation = response["continuation"]
            else:
                continuation = ""

            keep_going = (continuation != "")


        #The search returns read items as well, so if they only want unread
        #then remove read items
        if unread_only:
            items = [i for i in items if i["unread"]]

        #If there was no continuation, then just return the response to keep
        #all information intact
        if api_calls == 1:
            response["api_calls"] = api_calls
            response["items"] = items
            return response

        #If multiple api calls occured, then all I care about is the items since
        #the other information doesn't matter
        return {
            "items": items,
            "api_calls": api_calls
        }

    def get_feed_content(self, streamId, unreadOnly, newerThan, fields="", embedded="", enagement=""):
        '''return contents of a feed'''

        items = []
        keep_going = True
        continuation = ""
        api_calls = 0

        #This is for continuation
        #Keep grabbing more items until all are grabbed
        while keep_going and api_calls <= 20:
            response = self._make_call(self.fc.get_feed_content, streamId, unreadOnly, newerThan, fields, embedded, enagement, continuation)
            api_calls += 1

            if "items" in response:
                items.extend(response["items"])

            #Do we need to keep going to get more results?
            if "continuation" in response:
                continuation = response["continuation"]
            else:
                continuation = ""

            keep_going = (continuation != "")

        #If there was no continuation, then just return the response to keep
        #all information intact
        if api_calls == 1:
            response["api_calls"] = api_calls
            return response

        #If multiple api calls occured, then all I care about is the items since
        #the other information doesn't matter
        return {
            "items": items,
            "api_calls": api_calls
        }
    
    def mark_article_read(self, entryIds):
        '''Mark one or multiple articles as read'''
        return self._get_call(self.fc.mark_article_read, entryIds)
    
    def mark_article_unsaved(self, entryIds):
        '''Mark one or multiple articles as unsaved'''
        return self._get_call(self.fc.mark_article_unsaved, entryIds)
    
    def get_user_profile(self):
        '''return user's profile'''
        return self._make_call(self.fc.get_user_profile)