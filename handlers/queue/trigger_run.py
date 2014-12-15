import webapp2, os, logging, json
from utils.consts import *
from models.Feedler import Feedler
from models.Trigger import *

#Run a trigger
class TriggerRunHandler(webapp2.RequestHandler):
    def post(self):
        trigger = get_by_key_urlsafe(self.request.get("trigger_urlsafe"))
        if trigger is None:
            return

        trigger.run_block()

app = webapp2.WSGIApplication([
    ('/queue/trigger/run', TriggerRunHandler)
], debug=True)