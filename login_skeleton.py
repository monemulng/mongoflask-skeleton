#
# Remember that if you don't enable SSL (HTTPS), then all password will
# be sent in plaintext.
#
# Also remember to change 'app.secret_key' and reCAPTCHA settings if
# used.
#

from flask import Flask
from flask import request
from flask import render_template
from flask import redirect
from flask.ext.login import LoginManager, login_user, logout_user
from flask.ext.login import UserMixin, current_user, login_required
from pymongo import Connection
#from werkzeug.security import generate_password_hash
from werkzeug.security import check_password_hash 
import random, string
import datetime     
from flask import flash, url_for
from urlparse import urljoin
from forms import LoginForm
from forms import RECAPTCHA_Form
from flask import session

# Application settings:
app = Flask(__name__)
app.secret_key = 'CHANGE ME'  # Set the secret key, it is also used by
                              # LoginManager.
app.debug = True              # Set False before deployment
 

# Login manager settings:
login_manager = LoginManager()  
login_manager.session_protection = "strong"
login_manager.login_view = "/login"
login_manager.login_message = u"Please login."


# Database
con = Connection()
db = con.user_database
users = db.users

# Session config:
max_session_releases = 3  # Maximum number of valid secrets per user
max_secret_age_hours = 24.0  # Time for an secret to expire
min_login_retry_dur = 10  # Minimum time that must pass before a new
                          # attampt.

# Misc:
DEBUG = True

# reCAPTCHA setting:
ENABLE_RECAPTCHA = True  # If true, then the user will be taken to a
  #  reCAPTCH page instead of being asked to wait when trying to login too
  #  often.
RECAPTCHA_PUBLIC_KEY = "6LeYIbsSAAAAACRPIllxA7wvXjIE411PfdB2gt2J"  
    # required A public key.
RECAPTCHA_PRIVATE_KEY = "6LeYIbsSAAAAAJezaIq3Ft_hSTo0YtyeFG-JgRtu"  
    # required A private key.


class User(UserMixin):
    """This class represents a user. We'll populate it with data from
    the database.
    """
    def __init__(self, id):
        self.id = id
        self.name, self.secret = id.split("#")

    def is_active(self):
        print self.id
        return True

def check_password(user_doc, password):
    return check_password_hash(user_doc['saltedpw'], password)
      

def render(*args, **kwargs):
    kwargs['user'] = current_user.__dict__
    return render_template(*args, **kwargs)


@login_manager.user_loader
def load_user(public_id):
    """This function is required by the login manager plugin. This
    function is executed for each request that has a @login_required
    decorator to verify the user identity.
    """
    if DEBUG:
        print "Public ID: " + public_id
    split_pid = public_id.split("#")
    if not len(split_pid) == 2:
        return None  # Public id is not valid
    username, secret = split_pid
    user = users.find_one({u"username": username})
    print user
    if not user.has_key('secrets'):
        return None
    secrets = user['secrets']
    # Find the secret strings that have not expired:
    secret_strings = []
    for s in secrets:
        if s['created'] + datetime.timedelta(hours =
                max_secret_age_hours) > datetime.datetime.utcnow():
            secret_strings.append(s['value'])
    if secret in secret_strings:
        return User(public_id)
    else:
        return None  # Secret does not match


def generate_secret(length=32):
    """Returns a secret consisting of letters and numbers.
    """
    return ''.join(random.choice(string.letters + string.digits) \
            for x in range(length))


def generate_public_userid(user_doc):
    """
    Generates an public ID for the user, which is passed on to the
    client's browser. The ID also contains a secret, which is used to
    ensure that the ID is up to date. The secret should be updated when
    the user logs in, updates the password, or if the secret has
    expired.

    This method also updates the secret stored in the database.
    """
    delimiter = "#"
    username = user_doc['username']
    if delimiter in username:
        raise Exception("Username must not contain '%s'" % delimiter)
    # Update database with new secret and creation time:
    create_time = datetime.datetime.utcnow() 
    secret = {'value': generate_secret(), 'created': create_time}
    public_id = username + "#" + secret['value']
    # Here we should update the user db entry with secret
    if user_doc.has_key('secrets'):
        secrets = user_doc['secrets']
    else:
        secrets = []
    secrets.append(secret)
    secrets = secrets[-max_session_releases:]
    users.update({u'username': username}, {"$set": 
        {"secrets": secrets}})
    return public_id


def do_login_user(user_doc, password):
    """
    Returns true if user is successfully logged in.
    """
    if not check_password(user_doc, password):
        return False
    public_userid = generate_public_userid(user_doc)
    user = User(public_userid)
    if login_user(user):
        print "Logged in user: " + public_userid
        return True
    else:
        print "Failed to login user: " + public_userid
        return False

def get_next_url():
    next_url = url_for('index')
    target = session.pop('next', None)
    if target is not None:
            # Make sure it is on this server
            next_url = urljoin(request.host_url, target)
            print "next_url: ", next_url 
    session['next'] = request.args.get('next')
    return next_url
 
# Routes ----------------------------------------------------------------

                               
@app.route('/login', methods=['GET', 'POST'])
def login_wtf():
    next_url = get_next_url()
    form = LoginForm()
    capform = RECAPTCHA_Form() 
    is_cap = False
    if 'recaptcha_response_field' in request.form.keys():
        is_cap = True
        form = capform
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        # We should clean userid first?
        user_doc = users.find_one({"username": username})
        if not user_doc is None:
            # Make sure enough time has passed:
            last_attempt = None
            if user_doc.has_key('last_attempt'):
                last_attempt = user_doc['last_attempt']
            if (last_attempt is not None) and (not is_cap):
                if last_attempt + datetime.timedelta(seconds=
                    min_login_retry_dur) > datetime.datetime.utcnow():
                    if ENABLE_RECAPTCHA:
                        capform = RECAPTCHA_Form()
                        capform.username.data = username
                        capform.password.data = password
                        return render('recaptcha.html', form=capform) 
                    else:
                        flash('Please wait a while...')
                        return redirect(url_for('login'))
            users.update({u'username': username}, {"$set":
                {"last_attempt": datetime.datetime.utcnow()}})
            if do_login_user(user_doc, password):
                return redirect(next_url)
            else:
                flash('Authentication failed A')
                return render('loginwtf.html', form=LoginForm())
                #return redirect(url_for('login_wtf',
                #    next=request.args.get('next')))
        else:
            # No user with that username
            flash('Authentication failed');
            return render('loginwtf.html', form=form)   
    else:
        if is_cap:
            return render('recaptcha.html', form=capform)
        else:
            return render('loginwtf.html', form=form)


@app.route('/logout')
@login_required
def logout():
    """The sessions shared secret will also be deleted from the
    database. 
    """
    user = users.find_one({u'username': current_user.name})
    secrets = user['secrets']
    remove_us = filter(lambda secret:
            secret['value'] == current_user.secret, secrets)
    for rm in remove_us:
        secrets.remove(rm)
        if DEBUG:
            print "Removed secret %s for user %s." % (rm['value'], 
                    current_user.name) 
    logout_user()
    return redirect('/')
 

@app.route('/loginreq')
@login_required
def login_req():
    """The login_req decorator will only allow logged in users to access
    this method.
    """
    return render('login_req.html')


@app.route('/')
def index():
    return render('index.html')
 

if __name__ == '__main__':
    login_manager.init_app(app)
    app.config.from_object(__name__)
    app.run()



