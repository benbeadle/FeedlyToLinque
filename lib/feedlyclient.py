# -*- coding: UTF-8 -*-
import json

try:
  from google.appengine.api import urlfetch
  from google.appengine.ext import ndb
  import urllib, urlparse

  def content_fetch_async(url, method, params={}, data={}, headers={}):
    headers["Cache-Control"] = "no-cache,max-age=0"
    headers["Pragma"] = "no-cache"
    def combine_params(url, params):
      #Add params to the url
      url_parts = list(urlparse.urlparse(url))
      query = dict(urlparse.parse_qsl(url_parts[4]))
      query.update(params)
      url_parts[4] = urllib.urlencode(query)
      return urlparse.urlunparse(url_parts)

    url = combine_params(url, params)

    rpc = urlfetch.create_rpc()
    urlfetch.make_fetch_call(rpc, url, payload=json.dumps(data), method=method, headers=headers)
    return rpc

  def content_fetch(url, method, params={}, data={}, headers={}):
    return content_fetch_async(url, method, params, data, headers).get_result().content

  def json_fetch(url, method, params={}, data={}, headers={}):
    content = content_fetch(url, method, params=params, data=data, headers=headers)
    return json.loads(content)

  @ndb.tasklet
  def json_fetch_async(url, method, params={}, data={}, headers={}):
    result = yield content_fetch_async(url, method, params=params, data=data, headers=headers)
    raise ndb.Return(json.loads(result.content))

except:
  import requests

  def content_fetch(url, method, params={}, data={}, headers={}):
    response = requests.request(method, url, params=params, data=json.dumps(data), headers=headers)
    return response

  def json_fetch(url, method, params={}, data={}, headers={}):
    content = content_fetch(url, method, params=params, data=data, headers=headers)
    return content.json()


class FeedlyClient(object):
    def __init__(self, **options):
        self.client_id = options.get('client_id')
        self.client_secret = options.get('client_secret')
        self.sandbox = options.get('sandbox', True)
        if self.sandbox:
            default_service_host = 'sandbox.feedly.com'
        else:
            default_service_host = 'cloud.feedly.com'
        self.service_host = options.get('service_host', default_service_host)
        self.additional_headers = options.get('additional_headers', {})
        self.token = options.get('token')
        self.secret = options.get('secret')

    def get_code_url(self, callback_url):
        scope = 'https://cloud.feedly.com/subscriptions'
        response_type = 'code'
        
        request_url = '%s?client_id=%s&redirect_uri=%s&scope=%s&response_type=%s' % (
            self._get_endpoint('v3/auth/auth'),
            self.client_id,
            callback_url,
            scope,
            response_type
            )        
        return request_url
    
    def get_access_token(self,redirect_uri,code):
        params = dict(
                      client_id=self.client_id,
                      client_secret=self.client_secret,
                      grant_type='authorization_code',
                      redirect_uri=redirect_uri,
                      code=code
                      )
        
        quest_url=self._get_endpoint('v3/auth/token')
        return json_fetch(quest_url, "post", params=params)
    
    def refresh_access_token(self,refresh_token):
        '''obtain a new access token by sending a refresh token to the feedly Authorization server'''
        params = dict(
                      refresh_token=refresh_token,
                      client_id=self.client_id,
                      client_secret=self.client_secret,
                      grant_type='refresh_token',
                      )
        quest_url=self._get_endpoint('v3/auth/token')
        return json_fetch(quest_url, "post", params=params)
    
    
    def get_user_subscriptions(self,access_token):
        '''return list of user subscriptions'''
        headers = {'Authorization': 'OAuth '+access_token}
        quest_url=self._get_endpoint('v3/subscriptions')
        return json_fetch(quest_url, "get", headers=headers)

    def get_endpoint_async(self, access_token, endpoint, params={}):
        headers = {'Authorization': 'OAuth '+access_token}
        quest_url = self._get_endpoint(endpoint)
        return json_fetch_async(quest_url, "get", params=params, headers=headers)

    def get_endpoint(self, access_token, endpoint, params={}):
        return self.get_endpoint_async(access_token, endpoint, params).get_result()
    
    def get_feed_content(self, access_token, streamId, unreadOnly, newerThan, fields="", embedded="", enagement="", continuation=""):
        '''return contents of a feed'''
        headers = {'Authorization': 'OAuth '+access_token}
        quest_url=self._get_endpoint('v3/streams/contents')
        params = dict(
                      streamId=streamId,
                      unreadOnly=unreadOnly,
                      newerThan=newerThan,
                      count=20
                      )
        if fields != "":
          params["fields"] = fields
        if embedded != "":
          params["embedded"] = embedded
        if enagement != "":
          params["enagement"] = enagement
        if continuation != "":
          params["continuation"] = continuation
        return json_fetch(quest_url, "get", params=params, headers=headers)
    
    def mark_article_read(self, access_token, entryIds):
        '''Mark one or multiple articles as read'''
        headers = {'content-type': 'application/json',
                   'Authorization': 'OAuth ' + access_token
        }
        quest_url = self._get_endpoint('v3/markers')
        params = dict(
                      action="markAsRead",
                      type="entries",
                      entryIds=entryIds,
                      )
        return content_fetch(quest_url, "post", data=params, headers=headers)
    
    def mark_article_unsaved(self, access_token, entryIds):
        '''Mark one or multiple articles as unsaved'''
        headers = {'content-type': 'application/json',
                   'Authorization': 'OAuth ' + access_token
        }
        quest_url = self._get_endpoint('v3/markers')
        params = dict(
                      action="markAsUnsaved",
                      type="entries",
                      entryIds=entryIds,
                      )
        return content_fetch(quest_url, "post", data=params, headers=headers)
    
    def save_for_later(self, access_token, user_id, entryIds):
        '''saved for later.entryIds is a list for entry id.'''
        headers = {'content-type': 'application/json',
                   'Authorization': 'OAuth ' + access_token
        }
        request_url = self._get_endpoint('v3/tags') + '/user%2F' + user_id + '%2Ftag%2Fglobal.saved'
        
        params = dict(entryIds=entryIds)
        return content_fetch(request_url, "put", data=params, headers=headers)
    
    def get_user_profile(self, access_token):
        '''return user's profile'''
        headers = {'content-type': 'application/json',
                   'Authorization': 'OAuth ' + access_token
        }
        request_url = self._get_endpoint('/v3/profile')
        
        return json_fetch(request_url, "get", headers=headers)

    def _get_endpoint(self, path=None):
        url = "https://%s" % (self.service_host)
        if path is not None:
            url += "/%s" % path
        return url
