import os

#Helper variable to change values based on whether we are on the development server or not
_is_dev = os.environ.get('SERVER_SOFTWARE','').startswith('Development')

#This key is used to store the current Feedler logged in to the sessions
#Use utils.consts.Crypt.iv() to generate a random value
FEEDLER_LOGIN_KEY = ""

#This is the cookie_key used for gaesessions
GAESESSIONS_KEY = ""

#The Feedly client ID and secret
FEEDLY_CLIENT_ID = "" if _is_dev else ""
FEEDLY_CLIENT_SECRET = "" if _is_dev else ""

#The alphabet used to convert numbers to a base62 representation and back
BASE62_ALPHABET = ""

#The Linque API link/send URL
#I'd stick with the appspot URL since there's currently an issue
#with python and the SSL cert on www.linque.me (as of 12/13/2014)
LINQUE_SEND_URL = "https://linqueme.appspot.com/api/v1/link/send"

#This is used to add an 'SDK' dropdown on the development server for easy access
#to the console and dataviewer
DEV_ADMIN_ROOT = "http://localhost:8006/"