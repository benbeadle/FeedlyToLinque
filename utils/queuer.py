from google.appengine.api.taskqueue import taskqueue


def run_trigger(trigger):
	params = {
		"trigger_key": trigger.key.urlsafe()
	}

	url = '/queue/trigger/run'
	taskqueue.add(url=url, params=params, queue_name="trigger-run")