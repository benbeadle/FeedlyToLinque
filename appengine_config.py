from lib.gaesessions import SessionMiddleware
import secrets

#Add GAESessions to help keep track of sessions
def webapp_add_wsgi_middleware(app):
	app = SessionMiddleware(app, cookie_key=secrets.GAESESSIONS_KEY)
	return app