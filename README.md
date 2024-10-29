# CArtei
Repository for our rental management software 


## Local development

To get started on your local host for development (not connected to LDAP):

```bash
pip install -r requirements.txt
cd src/cartei
LOCAL_DEV=true python manage.py migrate
LOCAL_DEV=true python manage.py create_tiles
LOCAL_DEV=true python manage.py runserver
```

when the server is running, you can create a user to log in with:

```bash
LOCAL_DEV=true python manage.py createsuperuser
```