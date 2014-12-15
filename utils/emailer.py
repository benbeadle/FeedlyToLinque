#A shortcut method to prepare the email for sending to
#reduce duplicate code
def _send_mail(feedler, subject, body, html_body):
	from google.appengine.api import mail
	from google.appengine.api import app_identity
	from utils.consts import ROOT

	app_id = app_identity.get_application_id()
	sender_address = "No Reply <no-reply@%s.appspotmail.com>" % app_id
	if feedler.first_name == "":
		to_address = feedler.email
	else:
		to_address = "%s <%s>" % (feedler.first_name, feedler.email)

	body = body.replace("%first_name%", feedler.first_name)
	body = body.replace("%root%", ROOT)

	html_body = html_body.replace("%first_name%", feedler.first_name)
	html_body = html_body.replace("%root%", ROOT)
	html_body = html_body.replace("\n", "<br />")

	html = "<!doctype html><html><head><title>%s</title></head><body>%s</body></html>" % (subject, html_body)

	mail.send_mail(sender_address, to_address, subject, body, html=html)

#The Feedler needs to reauthenticate their account since it somehow got
#disconnected
def need_to_authorize(feedler):
	subject = "Re-Authenticate Your Feedly Account"
	text_body = "Hi %first_name%,\n\nWe lost access to your Feedly account and can't run your Triggers anymore. To re-authenticate, please go to the following URL:\n\n%root%app?force=auth\n\nThanks, and have a great day!"
	html_body = "Hi %first_name%,\n\nWe lost access to your Feedly account and can't run your Triggers anymore. To re-authenticate, please go to the following URL:\n\n<a href='%root%app?force=auth' target='_blank'>%root%app?force=auth</a>\n\nThanks, and have a great day!"
	_send_mail(feedler, subject, text_body, html_body)

#The Feedler needs to reauthenticate their account since it somehow got
#disconnected
def trigger_error(trigger, error_msg):
	subject = "Trigger Disabled Due To Error"
	text_body = "Hi %first_name%,\n\nWhile running Trigger:\n\n%trigger_desc%\n\nthe following error occurred:\n\n%trigger_error%\n\nTo fix the error and re-enable the Trigger, you can edit it at the following URL:\n\n%root%app/edit/%trigger_id%\n\nThanks, and have a great day!"
	html_body = "Hi %first_name%,\n\nWhile running Trigger:\n\n%trigger_desc%\n\nthe following error occurred:\n\n%trigger_error%\n\nTo fix the error and re-enable the Trigger, you can edit it at the following URL:\n\n<a href='%root%app/edit/%trigger_id%' target='_blank'>%root%app/edit/%trigger_id%</a>\n\nThanks, and have a great day!"

	text_body = text_body.replace("%trigger_desc%", trigger.description)
	text_body = text_body.replace("%trigger_error%", error_msg)
	text_body = text_body.replace("%trigger_id%", trigger.id)
	html_body = html_body.replace("%trigger_desc%", trigger.description)
	html_body = html_body.replace("%trigger_error%", error_msg)
	html_body = html_body.replace("%trigger_id%", trigger.id)

	_send_mail(trigger.feedler, subject, text_body, html_body)