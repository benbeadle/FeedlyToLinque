#
# This file contains common methods and variables used around the site
#
import time, math, os, logging, json, re, hashlib, base64, secrets
from datetime import datetime
from random import random as rand
from uuid import uuid4
from google.appengine.ext import ndb
from google.appengine.ext.webapp import template
from Crypto import Random
from Crypto.Cipher import AES

#Easy getter to check if I'm running on the development server or live server
IS_DEV = os.environ.get('SERVER_SOFTWARE','').startswith('Development')
ENVIRONMENT = "local" if IS_DEV else "live"

#Simple getter to get the correct root
#Feedly requires port 8080 be used: http://developer.feedly.com/v3/sandbox/
ROOT = "http://localhost:8080/" if IS_DEV else "https://feedlytolinque.appspot.com/"

#For development, Feedly Sandbox only allows the root to be used as a redirect
FEEDLY_REDIRECT_URI = ROOT

#How often should Triggers run in minutes
RUN_TRIGGER_EVERY_MINUTE = 10

#How many Triggers for the cron job to fetch at most
#If you don't want a limit, set this to None
TRIGGER_CRON_LIMIT = 100

#Pre-joined path to reference HTML files
HTML_FILE = os.path.join(os.path.dirname(__file__), "..", "site", "html", "{0}") + ".html"

#Helper method to get the geedly client depending on whether a token is passed in
def get_feedly_client(token=None):
    import fix_path, secrets
    from lib.feedlyclient import FeedlyClient

    if token:
        return FeedlyClient(token=token, sandbox=IS_DEV)
    else:
        return FeedlyClient(client_id=secrets.FEEDLY_CLIENT_ID, client_secret=secrets.FEEDLY_CLIENT_SECRET, sandbox=IS_DEV)


#Render the template using Django
#This allows using Django 1.5 and {% verbatim %}
def render_template(handler, page_name, params={}, trigger_template=None):
    from google.appengine.ext.webapp import template
    
    #Add params used in the templates
    params["root"] = handler.request.host_url
    params["js"] = params["css"] = ""
    params["page_name"] = page_name
    params["is_dev"] = IS_DEV

    #Add another navbar dropdown on the development server
    #for easy access to the SDK console and dataviewer
    if IS_DEV:
        params["admin_root"] = secrets.DEV_ADMIN_ROOT

    if trigger_template is not None:
        trigger_path = HTML_FILE.format("triggers/%s" % trigger_template)
        trigger_render = template.render(trigger_path, params)

        params["trigger_fields"] = trigger_render

    #Render the page
    page_path = HTML_FILE.format(page_name)
    page_render = template.render(page_path, params)

    #Render the template
    template_path = HTML_FILE.format("template")
    template_render = template.render(template_path, params)
    
    #Combine the renderings and output
    handler.response.out.write(template_render.replace("[PAGE]", page_render))

    return

#Helper gaesession shortcuts methods
def session_get(id, default=None):
    from lib.gaesessions import get_current_session
    return get_current_session().get(id, default)
def session_set(id, val, regen_id=False):
    from lib.gaesessions import get_current_session
    s = get_current_session()
    s[id] = val
    #Optionally regenerate the id for security
    if regen_id:
        s.regenerate_id()
def session_delete(id):
    from lib.gaesessions import get_current_session
    s = get_current_session()
    if id in s:
        del s[id]
def session_get_and_delete(id, default=None):
    v = session_get(id, default)
    session_delete(id)
    return v


#Helper methods to convert DateTime between unix timestamps and back
def to_unix_seconds(dt):
    epoch = datetime.utcfromtimestamp(0)
    delta = dt - epoch
    return int(delta.total_seconds())
def to_unix(dt):
    return to_unix_seconds(dt) * 1000
def from_unix(sec):
    try:
        return datetime.fromtimestamp(int(sec) / 1000)
    except:
        return None


#Converts a number to base62
def to_base62(num):
    from secrets import BASE62_ALPHABET
    if (num == 0):
        return BASE62_ALPHABET[0]
    arr = []
    base = len(BASE62_ALPHABET)
    while num:
        rem = num % base
        num = num // base
        arr.append(BASE62_ALPHABET[rem])
    arr.reverse()
    return ''.join(arr)

#Converts the base62-encoded string to the number representation
#Returns -1 if invalid
def from_base62(st):
    from secrets import BASE62_ALPHABET
    base = len(BASE62_ALPHABET)
    strlen = len(st)
    num = 0

    idx = 0
    for char in st:
        power = (strlen - (idx + 1))
        try:
            num += BASE62_ALPHABET.index(char) * (base ** power)
        except:
            return -1;
        idx += 1

    return num

#Returns either None or an object given the urlsafe string of the key
#If kind is not None, then only return the object if it's of that kind
def get_by_key_urlsafe(urlsafekey, get=True):
    try:
        k = ndb.Key(urlsafe=urlsafekey)
    except:
        return None

    #Either return the model or the ndb key
    if get:
        return k.get()

    return k

#The AES Encrypt/Decrypt class
class Crypt:

    @classmethod
    def en(cls, text, key, iv=None):
        pad = lambda s: s + (AES.block_size - len(s) % AES.block_size) * chr(AES.block_size - len(s) % AES.block_size)
        text = pad(text)

        enc_iv = iv if iv is not None else cls.iv()
        cipher = AES.new(key, AES.MODE_CBC, enc_iv)

        inc_iv = "" if iv is not None else enc_iv
        return base64.b64encode(inc_iv + cipher.encrypt(text))

    @classmethod
    def de(cls, enc, key, iv=None):
        unpad = lambda s : s[0:-ord(s[-1])]
        #Return empty string if padding incorrect
        try:
            enc = base64.b64decode(enc)
        except:
            return ""

        #If iv isn't supplied, then it's in the string
        if iv is None:
            iv = enc[:AES.block_size]
            enc = enc[AES.block_size:]

        try:
            cipher = AES.new(key, AES.MODE_CBC, iv)
            return unpad(cipher.decrypt(enc))
        except:
            return ""

    @classmethod
    def iv(self):
        return Random.new().read(AES.block_size)