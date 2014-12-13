#
# This file is the site handler to display/interact with users.
#
import webapp2, os, logging, json
from utils.consts import *
from models.Feedler import Feedler, FeedlerHandler
from models.Trigger import *

#This is the main handler which shows the user's their Triggers and allows
#them to create a new one
class AppHandler(FeedlerHandler):
    def get(self):
        #I don't want the "/" at the end
        if self.request.path == "/app/":
            self.redirect("/app", abort=True)

        params = {
            "triggers": self.feedler.all_triggers()
        }

        self.render_template("app", params)

#This is the handler where they create a new Trigger
class AppNewHandler(FeedlerHandler):
    def get(self, trigger_cls_id=""):

        #Get the Trigger's information
        triggers = Trigger.triggers_to_json()

        #If there's no trigger cld_id passed in, then
        #they need to select one
        if trigger_cls_id == "":
            params = {
                "triggers": triggers
            }
            self.render_template("new", params)
        #Make sure the cls_id is valid before creating!
        elif trigger_cls_id not in triggers:
            self.redirect("/app/new", abort=True)
        else:
            #Output this Trigger's description
            params = {
                "trigger_desc": triggers[trigger_cls_id]["description"],
                "trigger_cls_id": trigger_cls_id,
                "creating": True
            }

            #Customize the parameters to pass to the page since different
            #triggers have custom data to display to the user
            triggers[trigger_cls_id]["model"].customize_params(self.feedler, params)

            self.render_trigger(trigger_cls_id, False, params)


    def post(self, trigger_cls_id=""):
        triggers = Trigger.triggers_to_json()

        #There shouldn't be a post unless it's a valid trigger
        if trigger_cls_id == "" or trigger_cls_id not in triggers:
            self.redirect("/app/new", abort=True)
        
        user_desc = self.request.get("user_desc", "")
        device_name = self.request.get("device_name", "")

        params = {
            "user_desc": user_desc,
            "device_name": device_name
        }

        #Make sure the user entered a decription
        if user_desc == "":
            params["error"] = "Please enter a short trigger description"
        else:
            TriggerCls = triggers[trigger_cls_id]["model"]

            #Attempt to create and validate all input from the request
            trigger = TriggerCls.create(self.feedler, user_desc, device_name, self.request)
            err = trigger.validate_and_save(self.request)

            #If err is blank, then all user input was valid and the trigger
            #was saved
            if err == "":
                self.redirect("/app", abort=True)

            params["trigger"] = trigger
            params["error"] = err

        #Add the description and cls_id just like the get method
        params.update({
            "trigger_desc": triggers[trigger_cls_id]["description"],
            "trigger_cls_id": trigger_cls_id
        })

        #Customize the parameters to pass to the page since different
        #triggers have custom data to display to the user
        triggers[trigger_cls_id]["model"].customize_params(self.feedler, params)

        self.render_trigger(trigger_cls_id, False, params)

#This handler allows the user to edit/update/delete a Trigger
#Very similar to the above AppNewHandler
class AppEditHandler(FeedlerHandler):
    def get(self, trigger_id):
        trigger = Trigger.get_by_base62(self.feedler, trigger_id)

        #Make sure it's a valid Trigger
        if trigger is None:
            self.redirect("/app", abort=True)

        params = {
            "trigger": trigger
        }

        #Customize the params since Trigger's have custom data
        trigger.__class__.customize_params(self.feedler, params)
        
        self.render_trigger(trigger.cls_id, True, params)

    def post(self, trigger_id):
        trigger = Trigger.get_by_base62(self.feedler, trigger_id)

        if trigger is None:
            self.redirect("/app", abort=True)

        #If they hit the delete button, then delete the Trigger
        #and go back to the Trigger list
        deleting = self.request.get("trigger_action", "save") == "delete"
        if deleting:
            trigger.delete()
            self.redirect("/app", abort=True)

        params = {
            "trigger": trigger
        }

        #Make sure they entered valid data before saving it
        edit_err = trigger.validate_and_save(self.request)
        if edit_err == "":
            self.redirect("/app", abort=True)

        params["error"] = edit_err
        trigger.__class__.customize_params(self.feedler, params)

        self.render_trigger(trigger.cls_id, True, params)

#Shows the user's settings
class AppSettingsHandler(FeedlerHandler):
    def get(self):
        params = {
            "first_name": self.feedler.first_name,
            "email_address": self.feedler.email,
            "linque_api_key": self.feedler.linque_api_key
        }
        self.render_template("settings", params)

    def post(self):
        first_name = self.request.get("first_name", "")
        email_address = self.request.get("email_address", "")
        linque_api_key = self.request.get("linque_api_key", "")

        params = {
            "first_name": first_name,
            "email_address": email_address,
            "linque_api_key": linque_api_key
        }

        #Make sure all of the input was valid before updating
        #the settings
        if first_name == "":
            params["error"] = "Please enter your first name"
        elif email_address == "":
            params["error"] = "Please enter your email address"
        elif linque_api_key == "":
            params["error"] = "Please enter your Linque API key"
        else:
            #Save the new settings and go back to the Trigger list
            self.feedler.first_name = first_name
            self.feedler.email = email_address
            self.feedler.linque_api_key = linque_api_key
            self.feedler.put()

            self.redirect("/app", abort=True)

        self.render_template("settings", params)

class LogoutHandler(FeedlerHandler):
    def get(self):
        Feedler.log_out()
        self.redirect("/")

#The main handler is what shows the welcome page and
#parses the code from Feedly Auth
class MainHandler(webapp2.RequestHandler):
    def get(self):

        #Since Feedly Sandbox only allows redirects to the root,
        #check if there's a code. If so, then attempt to finish
        #authentication
        code = self.request.get('code','')
        if code:
            feedly = get_feedly_client()

            #Get the access token (and data)
            res_access_token = feedly.get_access_token(FEEDLY_REDIRECT_URI, code)
            if 'errorCode' not in res_access_token:

                #If there wasn't an error, then create their Feedler account
                #and log them in then go to the app
                feedler = Feedler.get_or_create(res_access_token)
                feedler.log_in()
                
                #If the Feedly account doesn't have all the info we need,
                #then send them to the settings page
                if feedler.force_settings():
                    self.redirect("/app/settings", abort=True)

                self.redirect("/app", abort=True)

            else:
                logging.error(res_access_token["errorCode"])

            #If there was an error grabbing the access code, then just
            #remove the code from the url
            self.redirect("/")

        render_template(self, "main")
    
app = webapp2.WSGIApplication([
    ('/logout', LogoutHandler),
    ('/app/settings', AppSettingsHandler),
    ('/app/new', AppNewHandler),
    ('/app/new/(.*)', AppNewHandler),
    ('/app/edit/(.*)', AppEditHandler),
    ('/app', AppHandler),
    ('/app/', AppHandler),
    ('.*', MainHandler)
], debug=True)