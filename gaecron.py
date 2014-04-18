# -*- coding: utf-8 -*-

"""
gaecron.py: Web Cron Service on Google App Engine

License: The MIT license
Copyright (c) 2010 furyu-tei
"""

__author__ = 'furyutei@gmail.com'
__version__ = '0.0.2a'


import logging
import yaml
import os,cgi,re,urllib
import time,datetime
import random,hashlib
#import hmac,base64,sha
import wsgiref.handlers

"""
# use_library()だと0.96では変わらず警告が出る→appengine_config.pyで対応
#from google.appengine.dist import use_library
##use_library('django', '1.2')
#use_library('django', '0.96')
"""

from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.api import users
from google.appengine.api import urlfetch
from google.appengine.api import memcache
from google.appengine.api import mail
#from google.appengine.api.labs import taskqueue
from google.appengine.api.taskqueue import taskqueue
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.mail_handlers import InboundMailHandler
 
from django.utils import simplejson

from gaetimer import GAE_Timer,timer_maintenance,timer_initialize,set_maintenance_mode
from gaetimer import fetch_rpc

#{ // option parameters

CONFIG_FILE = u'gaecron.yaml' # 設定ファイル

PATH_BASE = u''               # 基準となるPATH(u''はルート)
"""
  PATH_BASEが空白(u'')の場合は、http://(appid).appspot.com/ がトップページ。
  PATH_BASE = u'/gc' とすると、http://(appid).appspot.com/gc/ がトップページ。
  変更した場合、app.yaml、cron.yaml の設定も併せて変更すること。
  例えば、PATH_BASE = u'/gc' とした場合は、

■ app.yaml の handlers: 下の設定
- url: /gc/(check|restore)_timer.*
  script: gaecron.py
  login: admin

- url: /gc/.*
  script: gaecron.py
  
■ cron.yaml の cron: 下の設定
  既存のcron.yamlを使用していて以下の記述が残っている場合、削除またはコメントアウトすること。
- description: check and restore timer
  url: /check_timer
  schedule: every 30 minutes

"""

PATH_IMAGE = "/image"       # 画像をおくPATH
PATH_CSS = "/css"           # CSSファイルをおくPATH
PATH_SCRIPT = "/script"     # SCRIPT をおくPATH
PATH_HTML = "/html"         # HTML をおくPATH (現状未使用)

#} // end of option parameters


#{ // general parameters

DEBUG_FLAG = False          # for webapp.WSGIApplication()
DEBUG_LEVEL = logging.DEBUG # for logger
DEBUG=True                  # False:  disable log() (wrapper of logging.debug())

NAME_APPLICATION_J = u'GAE-Cron'
NAME_APPLICATION_E = u'GAE-Cron'

PATH_TOP = PATH_BASE + u'/'
PATH_USER_BASE = PATH_BASE + u'/user'
PATH_USER_FORMAT = PATH_USER_BASE + u'/%s/'
PATH_CHECK_TIMER = PATH_BASE + u'/check_timer'
PATH_RESTORE_TIMER = PATH_BASE + u'/restore_timer'
PATH_REQUEST_SERV_INFO = PATH_BASE + u'/req_serv_info'
PATH_MAIL_BASE = u'/_ah/mail'
PATH_START_REPORT = PATH_MAIL_BASE + u'/gaecron.+'
PATH_STOP_REPORT = PATH_BASE + u'/stop_report'

PATH_DIARY_BASE = "http://d.hatena.ne.jp/furyu-tei"

DIR_TEMPLATE = 'template/'

TEMPLATE_TOP = u'gc-top.html'
TEMPLATE_USER_HEADER = u'gc-user-header.html'
TEMPLATE_USER_FORM = u'gc-user-form.html'
TEMPLATE_USER_FOOTER = u'gc-user-footer.html'
TEMPLATE_STATUS = u'status.html'

HTML_CREDITS="""
Presented by <a href="%(diary)s/"><img src="%(image)s/profile_s.gif" border="0" border="0" />風柳</a>
【<a href="%(diary)s/20100115/gaecronclub">関連記事</a>】
<a href="http://code.google.com/intl/ja/appengine/"><img src="%(image)s/appengine-noborder-120x30.gif" alt="Powered by Google App Engine" title="Powered by Google App Engine" border="0" /></a>
""" % {'image':PATH_IMAGE,'diary':PATH_DIARY_BASE}

CONTENT_TYPE_HTML = 'text/html; charset=utf-8'
CONTENT_TYPE_PLAIN  = 'text/plain; charset=utf-8'
CONTENT_TYPE_JS ='application/x-javascript; charset=utf-8'

DEFAULT_REDIRECT_WAIT = 3 # seconds

LIMIT_DB_FETCH = 500
MAX_RESTORE_NUM_PER_CYCLE = 2 # 1サイクルでチェックまたは再設定する最大ユーザ数（※必ず2以上を設定すること）

DEFAULT_MAX_USER = 50
DEFAULT_TIMER_PER_USER = 5

MAX_USER = DEFAULT_MAX_USER                      # 許容ユーザ数
MAX_TIMER_PER_USER = DEFAULT_TIMER_PER_USER      # 1ユーザ辺りの設定数

MAX_REPORT_URL = 3

NAMESPACE = 'gae_cron'

ISOFMT = '%Y-%m-%dT%H:%M:%S'

strptime = datetime.datetime.strptime
utcnow = datetime.datetime.utcnow
timedelta = datetime.timedelta

#} // end of general parameters


#{ // datastore
class dbGaeCronSession(db.Expando):
  user = db.UserProperty()
  authkey = db.StringProperty()
  date = db.DateTimeProperty(auto_now_add=True)


class dbGaeCronUser(db.Expando):
  user = db.UserProperty()
  user_id = db.StringProperty()
  email = db.StringProperty()
  nickname = db.StringProperty()
  authkey = db.StringProperty()
  cookie = db.TextProperty()
  croninfo = db.TextProperty()
  """
  {'0':{
    'url':'http://...', # target URL
    'valid':1,          # 0/1
    'kind':'cycle',     # 'cycle'/'cron'
    'cycle_info':{
      'cycle':10,       # min
    },
    'cron_info':{
      'min'  :'*',
      'hour' :'*',
      'day'  :'*',
      'month':'*',
      'wday' :'*',
      'tz_hours':9,
    },
    'tid':'...',        # timer id
    #'ns':'...',         # namespace of timer
  },...}
  """
  update_user = db.UserProperty(auto_current_user=True)
  update = db.DateTimeProperty(auto_now=True)
  date = db.DateTimeProperty(auto_now_add=True)


class dbGaeCronReportInfo(db.Expando):
  dest_url = db.StringProperty()
  dest_id = db.StringProperty()
  authkey = db.StringProperty()
  date = db.DateTimeProperty(auto_now_add=True)


#} // end of datastore


#{ // def log()
def log(*args):
  if not DEBUG: return
  for arg in args:
    try:
      logging.debug(arg)
    except Exception, s:
      try:
        logging.error(u'*** Error in log(): %s' % (unicode(s)))
      except:
        pass
#} end of def log()


#{ // def loginfo()
def loginfo(*args):
  for arg in args:
    try:
      logging.info(arg)
    except Exception, s:
      try:
        logging.error(u'*** Error in loginfo(): %s' % (unicode(s)))
      except:
        pass
#} // end of def loginfo()


#{ // def logerr()
def logerr(*args):
  for arg in args:
    try:
      logging.error(arg)
    except Exception, s:
      try:
        logging.error(u'*** Error in logerr(): %s' % (unicode(s)))
      except:
        pass
#} end of def logerr()


#{ // def load_config()
def load_config():
  global MAX_USER
  global MAX_TIMER_PER_USER
    
  flg = False
  while True:
    try:
      conf_file = os.path.join(os.path.dirname(__file__), CONFIG_FILE)
      conf = yaml.load(open(conf_file).read().decode('utf-8'))
    except Exception, s:
      logerr(u'load_config(): %s' % (str(s)))
      break
    
    if not conf:
      conf = {}
    
    try:
      max_user = int(conf.get('MaxUser',DEFAULT_MAX_USER))
    except:
      max_user = 0
    if 0<max_user:
      MAX_USER = max_user
    
    try:
      max_timer = int(conf.get('MaxTimerPerUser',DEFAULT_TIMER_PER_USER))
    except:
      max_timer = 0
    if 0<max_timer:
      MAX_TIMER_PER_USER = max_timer
    
    flg = True
    break
  return flg

#} // end of def load_config()


#{ // def quote_param()
def quote_param(param):
  if not isinstance(param, basestring):
    param=unicode(param)
  return urllib.quote(param.encode('utf-8'),safe='~')
#} // end of def quote_param()


#{ // cgi_escape()
def cgi_escape(source_str,escape_quote=True):
  if isinstance(source_str,basestring):
    return cgi.escape(source_str,escape_quote)
  return source_str
#} // end of cgi_escape()


#{ // deep_escape()
def deep_escape(target,escape_quote=True):
  if isinstance(target,dict):
    keys=target.keys()
  elif isinstance(target,(list,tuple)):
    keys=range(len(target))
  else:
    return cgi_escape(target,escape_quote)
  for key in keys:
    if key == 'html': continue
    target[key]=deep_escape(target[key])
  return target
#} // end of deep_escape()


#{ // def datetime_to_isofmt()
def datetime_to_isofmt(t):
  try:
    return t.strftime(ISOFMT)
  except:
    return utcnow().strftime(ISOFMT)
#} // end of def datetime_to_isofmt()


#{ // def isofmt_to_datetime()
def isofmt_to_datetime(isofmt):
  try:
    return strptime(isofmt,ISOFMT)
  except:
    return utcnow()
#} // end of def isofmt_to_datetime()


#{ // def dbPut()
def dbPut(item,retry=2):
  for ci in range(retry):
    try:
      db.put(item)
      break
    except Exception, s:
      logerr(u'dbPut(): %s' % (str(s)))
      time.sleep(0.1)
#} // end of dbPut()


#{ // def dbDelete()
def dbDelete(items,retry=2):
  for ci in range(retry):
    try:
      db.delete(items)
      break
    except Exception, s:
      logerr(u'dbDelete(): %s' % (str(s)))
      time.sleep(0.1)
#} // end of dbDelete()


#{ // def common_init()
def common_init(self):
  (req,rsp) = (self.request,self.response)
  (rheaders,rcookies) = (req.headers,req.cookies)
  
  self.currentpath=os.path.dirname(__file__)
  self.tplpath=os.path.join(self.currentpath,DIR_TEMPLATE)
  self.urlbase=re.sub(u'[?#].*$','',req.url)
  self.action=re.sub(u'/[^/]*$',r'/',self.urlbase)
  self.urlroot=re.sub(u'(https?://[^/]*).*$',r'\1',req.url)
  self.sub_domain=re.sub(u'^https?://([^./]+).*$', r'\1', self.urlroot)
  self.login_url=users.create_login_url(req.uri)
  self.logout_url=users.create_logout_url(req.uri)
  self.user=users.get_current_user()
  self.is_admin = users.is_current_user_admin()
  
  return (req,rsp,rheaders,rcookies)
#} // end of def common_init()


#{ // def render_output_html()
def render_output_html(self,status_code,template_filename,template_values=None,render_only=False):
  if not render_only:
    rsp = self.response
    if status_code:
      rsp.set_status(int(status_code))
  
  if not template_values:
    template_values = {}
  
  template_values.update({
    'toppage': PATH_TOP,
    'aplname': NAME_APPLICATION_J,
    'aplname_e': NAME_APPLICATION_E,
    'credits': HTML_CREDITS,
    'max_user': MAX_USER,
    'max_cron': MAX_TIMER_PER_USER,
    'urlroot': self.urlroot,
    'urlbase': self.urlbase,
    'action': self.action,
    'login_url': self.login_url,
    'logout_url': self.logout_url,
    'user': self.user,
    'is_admin': self.is_admin,
    'user_base':PATH_USER_BASE,
    'image': PATH_IMAGE,
    'css': PATH_CSS,
    'script': PATH_SCRIPT,
    'html': PATH_HTML,
    'version': __version__,
  })
  if self.user:
    template_values.update({
      'email': self.user.email(),
      'nickname': self.user.nickname(),
      'user_id': self.user.user_id(),
    })
  
  template_file = os.path.join(self.tplpath,template_filename)
  output_html = template.render(template_file,template_values)
  
  if not render_only:
    rsp.headers['Content-Type'] = CONTENT_TYPE_HTML
    rsp.out.write(output_html)
  
  return output_html
  
#} // end of def render_output_html()


#{ // prn_html_status()

HTML_STATUS_CODES={
  '200': 'OK',
  '201': 'Created',
  '204': 'No Content',
  '302': 'Found',
  '307': 'Temporary Redirect',
  '400': 'Bad Request',
  '401': 'Unauthorized',
  '402': 'Payment Required',
  '403': 'Forbidden',
  '404': 'Not Found',
  '500': 'Internal Server Error',
  '503': 'Service Temporary Unavailable',
  '507': 'Insufficient Storage',
}

HTML_META_REFRESH_BASE = u'<meta http-equiv="Refresh" content="%d' % (DEFAULT_REDIRECT_WAIT) + u'; URL=%s" />'

def prn_html_status(self,status_code=None,explain=None,message=u'',url_redirect=None):
  rsp = self.response
  if not status_code:
    status_code = 404
  _scode = unicode(status_code)
  if not explain:
    explain = HTML_STATUS_CODES.get(_scode)
  if explain:
    html_status = u'%s: %s' % (_scode, explain)
  else:
    html_status = _scode
  
  if url_redirect:
    if not re.search(u'http',url_redirect):
      url_redirect = self.urlroot + url_redirect
    meta_refresh = HTML_META_REFRESH_BASE % (url_redirect)
  else:
    meta_refresh = u''
  
  template_values = {
    'html_status': cgi_escape(html_status),
    'meta_refresh': meta_refresh,
    'message': cgi_escape(message),
  }
  render_output_html(self,status_code,TEMPLATE_STATUS,template_values)
  
#} // end of def prn_html_status()


#{ // def prn_html
def prn_html(self,template_filename=None,template_values=None,status_code=None,explain=None,message=u'',url_redirect=None,quick_redirect=False):
  rsp = self.response
  if url_redirect and quick_redirect:
    if status_code:
      rsp.set_status(int(status_code))
    self.redirect(url_redirect)
    return
  
  if not template_filename:
    prn_html_status(self=self,status_code=status_code,explain=explain,message=message,url_redirect=url_redirect)
    return
  
  if not status_code:
    status_code = 200
  render_output_html(self,status_code,template_filename,template_values)

#} // end of def prn_html()


#{ // def getGaeCronSession()
def getGaeCronSession(user=None,create=True):
  if not user:
    return None
  try:
    db_gcs_list = dbGaeCronSession.all().filter('user = ',user).order('date').fetch(LIMIT_DB_FETCH)
  except Exception,s:
    logerr(u'getGaeCronSession(): %s' % str(s))
    db_gcs_list = dbGaeCronSession.all().filter('user = ',user).fetch(LIMIT_DB_FETCH)
    db_gcs_list.sort(lambda a,b:cmp(a.date,b.date))
  if 0<len(db_gcs_list):
    db_gcs = db_gcs_list.pop()
    if 0<len(db_gcs_list):
      dbDelete(db_gcs_list)
  else:
    db_gcs = None
  
  if not db_gcs and create:
    db_gcs = dbGaeCronSession(
      user = user,
      authkey = hashlib.sha224('%s%16x'%(user.email(),random.randint(0,0xffffffffffffffff))).hexdigest(),
    )
    dbPut(db_gcs)
  
  return db_gcs
#} // end of def getGaeCronSession()


#{ // def getGaeCronUser()
def getGaeCronUser(user=None,db_key=None,db_id=None,user_id=None,email=None,create=True,cookie=None,authkey=None):
  db_gc = None
  while True:
    if not user and email:
      user = users.User(email=email)
    
    if user:
      db_gc = dbGaeCronUser.all().filter('user = ',user).get()
      if db_gc: break
      if not user_id:
        user_id = unicode(user.user_id())
    
    if not db_key and db_id:
      db_key = db.Key.from_path('dbGaeCronUser',int(db_id))
    
    if db_key:
      db_gc = db.get(db_key)
      if db_gc: break
    
    if user_id:
      db_gc = dbGaeCronUser.all().filter('user_id = ',unicode(user_id)).get()
      if db_gc: break
    
    if not user or not create:
      break
    
    def _create_user(user,cookie,authkey):
      if not cookie:
        cookie = u''
      if not authkey:
        authkey = hashlib.sha224('%s%16x'%(user.email(),random.randint(0,0xffffffffffffffff))).hexdigest()
      db_gc = dbGaeCronUser(
        user = user,
        user_id = unicode(user.user_id()),
        email = user.email(),
        nickname = user.nickname(),
        authkey = authkey,
        cookie = db.Text(cookie),
        croninfo = db.Text(simplejson.dumps({})),
      )
      db_gc.put()
      return db_gc
    
    db_gc = db.run_in_transaction(_create_user,user=user,cookie=cookie,authkey=authkey)
    break
  
  if db_gc and cookie and db_gc.cookie!=cookie:
    db_gc.cookie = db.Text(cookie)
    dbPut(db_gc)
  
  return db_gc

#} // end of def getGaeCronUser()


#{ // def getGaeCronReportInfo()
def getGaeCronReportInfo(db_id=None,dest_url=None,dest_id=None,create=True):
  if not db_id and not dest_url:
    return None
  
  db_gcr = None
  if db_id:
    db_key = db.Key.from_path('dbGaeCronReportInfo',int(db_id))
    if db_key:
      db_gcr = db.get(db_key)
  elif dest_url:
    try:
      db_gcr_list = dbGaeCronReportInfo.all().filter('dest_url = ',dest_url).order('date').fetch(LIMIT_DB_FETCH)
    except Exception,s:
      logerr(u'getGaeCronReportInfo(): %s' % str(s))
      db_gcr_list = dbGaeCronReportInfo.all().filter('dest_url = ',dest_url).fetch(LIMIT_DB_FETCH)
      db_gcr_list.sort(lambda a,b:cmp(a.date,b.date))
      
    if 0<len(db_gcr_list):
      db_gcr = db_gcr_list.pop()
      if 0<len(db_gcr_list):
        dbDelete(db_gcr_list)
  
  if not db_gcr and create:
    if not dest_url or not dest_id:
      return None
    authkey = hashlib.sha224('%16x'%(random.randint(0,0xffffffffffffffff))).hexdigest()
    db_gcr = dbGaeCronReportInfo(
      dest_url = dest_url,
      dest_id = dest_id,
      authkey = authkey,
    )
    dbPut(db_gcr)
  
  return db_gcr
#} // end of def getGaeCronReportInfo()


#{ // def get_user_info()
def get_user_info():
  current_user_num = dbGaeCronUser.all().count()
  remain_user_num = MAX_USER - current_user_num
  if remain_user_num < 0:
    remain_user_num = 0
  
  return (current_user_num,remain_user_num)
#} // end of get_user_info()


#{ // def rpc_callback()
def rpc_callback(url,result):
  log(u'callback: "%s"' % (url))
  if isinstance(result,basestring):
    s_result = result
  elif result:
    try:
      s_result = u'code: %d' % (result.status_code)
    except:
      try:
        s_result = unicode(result)
      except:
        s_result = u'unknown error(1)'
  else:
    s_result = u'unknown error(2)'
  
  log(s_result)
#} // end of def rpc_callback()


#{ // def reportServiceInfos()
def reportServiceInfos(current_user_num=None,remain_user_num=None):
  load_config()
  rpcs = []
  if current_user_num == None:
    (current_user_num,remain_user_num) = get_user_info()
  
  db_gcr_list = dbGaeCronReportInfo.all().fetch(MAX_REPORT_URL)
  params = dict(
    max_user=MAX_USER,
    max_timer=MAX_TIMER_PER_USER,
    current_user_num=current_user_num,
    remain_user_num=remain_user_num,
  )
  log(u'report url number=%d' % (len(db_gcr_list)))
  for db_gcr in db_gcr_list:
    url = db_gcr.dest_url
    params.update(dict(id=db_gcr.dest_id,authkey=db_gcr.authkey))
    log(u'report to: "%s"' % (url))
    log(u'params:',params)
    rpc = fetch_rpc(url=url,method='POST',params=params,keyid=url,callback=rpc_callback)
    if rpc:
      rpcs.append(rpc)
  
  for rpc in rpcs:
    rpc.wait()
  
#} // end of def reportServiceInfos()


#{ // class redirectToTop()
class redirectToTop(webapp.RequestHandler):
  def get(self):
    (req,rsp,rheaders,rcookies) = common_init(self)
    
    prn_html(self,status_code=404,url_redirect=PATH_TOP)

#} // end of class redirectToTop()


#{ // class toppage()
class toppage(webapp.RequestHandler):
  def get(self):
    (req,rsp,rheaders,rcookies) = common_init(self)
    load_config()
    
    (current_user_num,remain_user_num) = get_user_info()
    
    user = self.user
    if user:
      log(u'Login User: user_id="%s" email="%s" nickname="%s"' % (unicode(user.user_id()),unicode(user.email()),unicode(user.nickname())))
    
    if remain_user_num<=0 and user and not self.is_admin:
      db_gc = getGaeCronUser(user=user,create=False)
      if not db_gc:
        logerr(u'no user data and remain user number=0')
        self.redirect(self.logout_url)
        return
    
    if self.is_admin:
      try:
        db_gc_list = dbGaeCronUser.all().order('date').fetch(LIMIT_DB_FETCH)
      except:
        db_gc_list = dbGaeCronUser.all().fetch(LIMIT_DB_FETCH)
        db_gc_list.sort(lambda a,b:cmp(a.date,b.date))
        
    else:
      db_gc_list = []
    
    tvalues = {
      'user_num': current_user_num,
      'remain_user_num': remain_user_num,
      'db_gc_list': db_gc_list,
      'restore_timer_url': PATH_RESTORE_TIMER,
      'return_url':req.url,
    }
    prn_html(self,TEMPLATE_TOP,tvalues)
    
#} // end of class toppage()


#{ // class userpage()
class userpage(webapp.RequestHandler):
  def _common(self):
    (req,rsp,rheaders,rcookies) = common_init(self)
    load_config()
    
    if req.get('trial')=='1':
      url=req.get('url')
      try:
        result=urlfetch.fetch(url=url,headers={'Cache-Control':'no-cache,max-age=0'},method=urlfetch.GET,allow_truncated=True,follow_redirects=True,deadline=10)
        result_str = u'HTTPステータスコード %d' % (result.status_code)
        if 200<=result.status_code<300:
          rsp.set_status(200)
        else:
          rsp.set_status(400)
      except Exception, s:
        rsp.set_status(400)
        result_str = cgi_escape(unicode(s))
      
      rsp.headers['Content-Type'] = CONTENT_TYPE_PLAIN
      rsp.out.write(result_str.encode('utf-8'))
      return
    
    class_name = ['even','odd']
    _noresult = u'(-)'
    
    gae_timer=GAE_Timer()
    def _get_last_status(cron_info):
      _valid = cron_info['valid']
      tid = cron_info['tid']
      
      #gae_timer=GAE_Timer()
      
      if 0<_valid and tid:
        #last_status = get_last_status(timerid=tid)
        last_status = gae_timer.get_last_status(timerid=tid)
        last_timeout = last_status['last_timeout']
        last_result = last_status['last_result']
        if not last_timeout:
          last_timeout = _noresult
          last_result = _noresult
        #next_time = get_next_time(timerid=tid)
        next_time = gae_timer.get_next_time(timerid=tid)
        if not next_time:
          next_time = _noresult
      else:
        last_timeout = _noresult
        last_result = _noresult
        next_time = _noresult
      
      tz_hours = cron_info['cron_info'].get('tz_hours',9)
      if 0<tz_hours:
        tz_hours = u'+%3.1f' % (tz_hours)
      else:
        tz_hours = u'%3.1f' % (tz_hours)
      
      return (last_timeout,last_result,next_time,tz_hours)
    
    user = self.user
    is_admin = self.is_admin
    mrslt = re.search(PATH_USER_FORMAT % (u'([^/]+)') + u'(.*)$',req.uri)
    if not mrslt:
      logerr(u'user id not found from path')
      prn_html(self,status_code=404,url_redirect=PATH_TOP)
      return
    user_id_from_path = mrslt.group(1)
    
    log(u'user_id_from_path=%s' % (user_id_from_path))
    user_id = None
    
    if is_admin:
      user_id = user_id_from_path
    else:
      if not user:
        logerr(u'no login')
        prn_html(self,status_code=401,url_redirect=PATH_TOP,quick_redirect = True)
        return
      user_id = unicode(user.user_id())
      if user_id!=user_id_from_path:
        logerr(u'%s != %s' % (user_id,user_id_from_path))
        url_redirect = PATH_USER_FORMAT % (user_id)
        logerr(u'unmatch user')
        prn_html(self,status_code=401,url_redirect=url_redirect)
        return
    
    db_gc = getGaeCronUser(user_id=user_id_from_path,create=False)
    if is_admin:
      if db_gc:
        user = self.user = db_gc.user
      elif not user:
        logerr(u'user data not found')
        prn_html(self,status_code=404,url_redirect=PATH_TOP,quick_redirect=True)
        return
    
    registered = True if db_gc else False
    
    db_gcs = None
    
    if db_gc:
      authkey = db_gc.authkey
    else:
      db_gcs = getGaeCronSession(user,create=True)
      authkey = db_gcs.authkey
    
    tvalues = {
      'unregister_url': self.action,
      'registered': registered,
      'authkey': authkey,
      'curtime': (utcnow()+timedelta(hours=+9)).strftime('%Y/%m/%d %H:%M(JST)'),
      'restore_timer_url': PATH_RESTORE_TIMER,
      'return_url':req.url,
    }
    
    if registered and req.get('unregister')==u'1':
      status_code = 400
      while True:
        if req.get('authkey') != authkey:
          logerr('authkey failure: %s vs %s' % (req.get('authkey',u''),authkey))
          break
        cron_info_dict = simplejson.loads(db_gc.croninfo)
        #dbDelete(db_gc)
        #gae_timer = GAE_Timer()
        rel_timer = gae_timer.rel_timer
        for cron_info in cron_info_dict.values():
          tid = cron_info.get('tid')
          if tid:
            rel_timer(tid)
        
        dbDelete(db_gc)
        log(u'### unregister %s' % (user.email()))
        reportServiceInfos()
        status_code=204
        break
      prn_html(self,status_code=status_code,url_redirect=PATH_TOP,quick_redirect=True)
      return
    
    if self.modify:
      status_code = 400
      while True:
        flg_create = False
        
        if req.get('authkey') != authkey:
          logerr('authkey failure: %s vs %s' % (req.get('authkey',u''),authkey))
          break
        
        if db_gcs:
          dbDelete(db_gcs)
        
        if not db_gc:
          (current_user_num,remain_user_num) = get_user_info()
          
          if remain_user_num<=0:
            #status_code = 507 # NG on GAE
            status_code = 403
            break
          db_gc = getGaeCronUser(user=user,create=True,cookie=rheaders.get('cookie'),authkey=authkey)
          if db_gc:
            flg_create = True
            log(u'### register %s' % (user.email()))
        
        if not db_gc:
          status_code = 503
          break
        
        db_gc.email = user.email()
        db_gc.nickname = user.nickname()
        
        cron_info_dict = simplejson.loads(db_gc.croninfo)
        
        #gae_timer = GAE_Timer()
        set_timer = gae_timer.set_timer
        rel_timer = gae_timer.rel_timer
        
        no = req.get('no','0')
        cron_info = cron_info_dict.get(no)
        if cron_info:
          tid = cron_info.get('tid')
          if tid:
            rel_timer(tid)
        
        _url = re.sub(u'(^\s+|\s+$)',r'',req.get('timerinfo_url'))
        _valid = int(req.get(u'valid'))
        if not re.search(u'^s?https?://',_url):
          _valid = 0
        _kind = req.get(u'kind')
        
        try:
          _cycle = int(req.get(u'cycle',10))
        except:
          _cycle = 10
        
        _min = req.get(u'min','*/10')
        _hour = req.get(u'hour','*')
        _day = req.get(u'day','*')
        _month = req.get(u'month','*')
        _wday = req.get(u'wday','*')
        try:
          _tz_hours = float(req.get(u'tz_hours','9'))
          if _tz_hours<-12 or 14<_tz_hours:
            _tz_hours = 9
        except:
          _tz_hours = 9
        
        #_tid = None
        if 0<_valid:
          _tid=u'%s-%s-%s' % (NAMESPACE,str(db_gc.key().id()),str(no))
          if _kind == 'cycle':
            _tid = set_timer(minutes=_cycle,url=_url,user_id=db_gc.email,user_info=no,timerid=_tid)
          else:
            _crontime = ' '.join([_min,_hour,_day,_month,_wday])
            _tid = set_timer(crontime=_crontime,url=_url,user_id=db_gc.email,user_info=no,tz_hours=_tz_hours,timerid=_tid)
          if not _tid:
            _valid = 0
        else:
          _tid = None
        
        cron_info = cron_info_dict[no]=dict(
          url=_url,
          valid=_valid,
          kind=_kind,
          cycle_info=dict(cycle=_cycle),
          cron_info=dict(min=_min,hour=_hour,day=_day,month=_month,wday=_wday,tz_hours=_tz_hours),
          tid=_tid,
          #ns=namespace,
        )
        
        db_gc.croninfo = db.Text(simplejson.dumps(cron_info_dict))
        dbPut(db_gc)
        
        if flg_create:
          reportServiceInfos(current_user_num+1,remain_user_num-1)
        
        if req.get('ajax')=='1':
          cnt=1+int(no)
          
          (last_timeout,last_result,next_time,tz_hours) = _get_last_status(cron_info)
          
          timerinfos = [dict(
            no=no,
            cnt=cnt,
            url=cron_info['url'],
            valid=cron_info['valid'],
            kind=cron_info['kind'],
            cycle=cron_info['cycle_info']['cycle'],
            min=cron_info['cron_info']['min'],
            hour=cron_info['cron_info']['hour'],
            day=cron_info['cron_info']['day'],
            month=cron_info['cron_info']['month'],
            wday=cron_info['cron_info']['wday'],
            tz_hours=tz_hours,
            cname=class_name[cnt%2],
            last_timeout=last_timeout,
            last_result=last_result,
            next_time=next_time,
            exist=True,
          ),]
          
          tvalues['timerinfos'] = deep_escape(timerinfos)
          
          prn_html(self,TEMPLATE_USER_FORM,tvalues)
          
          return
        
        status_code = 302
        break
      
      if 200<= status_code <300 or status_code == 302:
        prn_html(self,status_code=status_code,url_redirect=req.uri,quick_redirect=True)
      else:
        prn_html(self,status_code=status_code,url_redirect=req.uri)
      return
    
    timerinfos = []
    
    if db_gc:
      cron_info_dict = simplejson.loads(db_gc.croninfo)
    else:
      cron_info_dict = {}
    
    for ci in range(MAX_TIMER_PER_USER):
      no = str(ci)
      cnt = 1+ci
      cron_info = cron_info_dict.get(no)
      if cron_info:
        (last_timeout,last_result,next_time,tz_hours) = _get_last_status(cron_info)
        
        timerinfos.append(dict(
          no=no,
          cnt=cnt,
          url=cron_info['url'],
          valid=cron_info['valid'],
          kind=cron_info['kind'],
          cycle=cron_info['cycle_info']['cycle'],
          min=cron_info['cron_info']['min'],
          hour=cron_info['cron_info']['hour'],
          day=cron_info['cron_info']['day'],
          month=cron_info['cron_info']['month'],
          wday=cron_info['cron_info']['wday'],
          tz_hours=tz_hours,
          cname=class_name[cnt%2],
          last_timeout=last_timeout,
          last_result=last_result,
          next_time=next_time,
          exist=True,
        ))
      else:
        timerinfos.append(dict(
          no=no,
          cnt=cnt,
          url=u'',
          valid=0,
          kind='cycle',
          cycle=10,
          min='*/10',
          hour='*',
          day='*',
          month='*',
          wday='*',
          tz_hours=u'+9.0',
          cname=class_name[(1+ci)%2],
          last_timeout=_noresult,
          last_result=_noresult,
          next_time=_noresult,
          exist=False,
        ))
    
    tvalues['timerinfos'] = deep_escape(timerinfos)
    
    _header = render_output_html(self,200,TEMPLATE_USER_HEADER,tvalues,render_only=True)
    _form = render_output_html(self,200,TEMPLATE_USER_FORM,tvalues,render_only=True)
    _footer = render_output_html(self,200,TEMPLATE_USER_FOOTER,tvalues,render_only=True)
    
    rsp.headers['Content-Type'] = CONTENT_TYPE_HTML
    rsp.out.write(_header+_form+_footer)
  
  def get(self):
    self.modify = False
    self._common()
    
  def post(self):
    self.modify = True
    self._common()
  
#} // end of class userpage()


#{ // class checkTimer()
class checkTimer(webapp.RequestHandler):
  def get(self):
    (req,rsp,rheaders,rcookies) = common_init(self)
    pre_str = u'checkTimer: '
    
    rsp.set_status(200)
    loginfo(pre_str+u'start')
    """
    #max_num = MAX_RESTORE_NUM_PER_CYCLE
    #last_id = req.get('last_id')
    #if not last_id:
    #  db_gc_list = dbGaeCronUser.all().order('date').fetch(max_num)
    #  cnt = 0
    #  tcnt = 0
    #else:
    #  last_time = isofmt_to_datetime(req.get('last_time'))
    #  log(' last_id=%s' % (last_id))
    #  log(' last_time=%s' % (req.get('last_time')))
    #  db_gc_list = dbGaeCronUser.all().filter('date >=', last_time).order('date').fetch(max_num)
    #  cnt = int(req.get('cnt'),0)
    #  tcnt = int(req.get('tcnt'),0)
    #
    #timer_maintenance()
    #
    #gae_timer = GAE_Timer()
    #set_timer = gae_timer.set_timer
    #rel_timer = gae_timer.rel_timer
    #
    #for db_gc in db_gc_list:
    #  db_gc_id = str(db_gc.key().id())
    #  if db_gc_id == last_id:
    #    continue
    #  
    #  cnt += 1
    #  email = db_gc.email
    #  loginfo(u'%d: %s  %s' % (cnt,email,db_gc.date))
    #  
    #  flg_update = False
    #  cron_info_dict = simplejson.loads(db_gc.croninfo)
    #  
    #  #gae_timer = GAE_Timer()
    #  #set_timer = gae_timer.set_timer
    #  #rel_timer = gae_timer.rel_timer
    #  
    #  for (no,cron_info) in cron_info_dict.items():
    #  
    #    flg_set = False
    #    flg_rel_comp = False
    #    
    #    timer = None
    #    tid = cron_info['tid']
    #    
    #    if tid:
    #      gae_timer.rel_timer(tid)
    #      flg_rel_comp = True
    #      flg_set = True
    #      
    #    if cron_info['valid']==0:
    #      if timer:
    #        if not flg_rel_comp:
    #          rel_timer(tid)
    #        cron_info['tid'] = None
    #        flg_update = True
    #      continue
    #    
    #    _url = cron_info['url']
    #    if cron_info['kind'] == 'cycle':
    #      _cycle = cron_info['cycle_info']['cycle']
    #      _crontime = None
    #    else:
    #      _cycle = None
    #      _c = cron_info['cron_info']
    #      _crontime = ' '.join([_c['min'],_c['hour'],_c['day'],_c['month'],_c['wday']])
    #    
    #    while True:
    #      if not timer:
    #        flg_set = True
    #        break
    #      
    #      if timer.user_id != email or timer.user_info != no:
    #        # perhaps BUG
    #        break
    #      
    #      if timer.url != _url:
    #        flg_set = True
    #        break
    #      
    #      if _cycle:
    #        if timer.minutes != _cycle:
    #          flg_set = True
    #          break
    #      else:
    #        if timer.crontime != _crontime:
    #          flg_set = True
    #          break
    #      break
    #    
    #    if not flg_set:
    #      continue
    #    
    #    tvalue = None
    #    if timer:
    #      if flg_rel_comp:
    #        tvalue = timer.timeout
    #      else:
    #        rel_timer(tid)
    #    
    #    if _cycle:
    #      tid = set_timer(minutes=_cycle,url=_url,user_id=email,user_info=no,tvalue=tvalue)
    #    else:
    #      tid = set_timer(crontime=_crontime,url=_url,user_id=email,user_info=no,tz_hours=_c['tz_hours'],tvalue=tvalue)
    #    
    #    if tid:
    #      tcnt += 1
    #      loginfo(u'  timer(No.%d) update (timerid=%s)' % (1+int(no),tid))
    #    else:
    #      cron_info['valid'] = 0
    #      logerr(u'  timer(No.%d) set error' % (1+int(no)))
    #    
    #    cron_info['tid'] = tid
    #    
    #    flg_update = True
    #  
    #  if flg_update:
    #    db_gc.croninfo = db.Text(simplejson.dumps(cron_info_dict))
    #    dbPut(db_gc)
    #    logerr(u' => update user datastore')
    #  else:
    #    log(u' => no update')
    #  
    #  last_id = db_gc_id
    #  last_time = db_gc.date
    #
    #if max_num<=len(db_gc_list):
    #  str_rsp = pre_str+u'continue'
    #  url=PATH_CHECK_TIMER+'?last_id=%s&last_time=%s&cnt=%d&tcnt=%d' % (urllib.quote(last_id),urllib.quote(datetime_to_isofmt(last_time)),cnt,tcnt)
    #  log(u'call:"%s"' % (url))
    #  for ci in range(3):
    #    try:
    #      taskqueue.add(url=url,method='GET',headers={'X-AppEngine-TaskRetryCount':0})
    #      break
    #    except Exception, s:
    #      str_rsp = pre_str+u'taskqueue error: %s' % (str(s))
    #      pass
    #    time.sleep(1)
    #else:
    #  str_rsp = pre_str+u'end'
    #  log('set timer (success) number=%d' % (tcnt))
    #  reportServiceInfos()
    #
    #loginfo(str_rsp)
    """
    str_rsp=pre_str+u'/check_timerは廃止され、機能は/gaetimer/restoreに移行されました。cron.yamlの設定を変更して下さい。'
    loginfo(str_rsp)
    rsp.headers['Content-Type'] = CONTENT_TYPE_PLAIN
    rsp.out.write(str_rsp)
    
#} // end of class checkTimer()


#{ // class restoreTimer()
class restoreTimer(webapp.RequestHandler):
  def _common(self):
    (req,rsp,rheaders,rcookies) = common_init(self)
    pre_str = u'restoreTimer: '
    
    rsp.set_status(200)
    loginfo(pre_str+u'start')
    
    max_num = MAX_RESTORE_NUM_PER_CYCLE
    last_id = req.get('last_id')
    flg_first = False
    if not last_id:
      set_maintenance_mode(True)
      flg_first = True
      timer_initialize()
      db_gc_list = dbGaeCronUser.all().order('date').fetch(max_num)
      cnt = 0
      tcnt = 0
    else:
      last_time = isofmt_to_datetime(req.get('last_time'))
      log(' last_id=%s' % (last_id))
      log(' last_time=%s' % (req.get('last_time')))
      db_gc_list = dbGaeCronUser.all().filter('date >=', last_time).order('date').fetch(max_num)
      cnt = int(req.get('cnt'),0)
      tcnt = int(req.get('tcnt'),0)
    
    gae_timer = GAE_Timer()
    set_timer = gae_timer.set_timer
    rel_timer = gae_timer.rel_timer
    
    for db_gc in db_gc_list:
      db_gc_id = str(db_gc.key().id())
      if db_gc_id == last_id:
        continue
      
      cnt += 1
      email = db_gc.email
      loginfo(u'%d: %s  %s' % (cnt,email,db_gc.date))
      
      cron_info_dict = simplejson.loads(db_gc.croninfo)
      
      #gae_timer = GAE_Timer()
      #set_timer = gae_timer.set_timer
      #rel_timer = gae_timer.rel_timer
      
      for (no,cron_info) in cron_info_dict.items():
        tid = None
        if cron_info['valid']:
          timerid=u'%s-%s-%s' % (NAMESPACE,db_gc_id,str(no))
          if cron_info['kind'] == 'cycle':
            #tid = set_timer(minutes=cron_info['cycle_info']['cycle'],url=cron_info['url'],user_id=email,user_info=no)
            tid = set_timer(minutes=cron_info['cycle_info']['cycle'],url=cron_info['url'],user_id=email,user_info=no,timerid=timerid,sem=False,save_after=True)
          else:
            _c = cron_info['cron_info']
            _crontime = ' '.join([_c['min'],_c['hour'],_c['day'],_c['month'],_c['wday']])
            #tid = set_timer(crontime=_crontime,url=cron_info['url'],user_id=email,user_info=no,tz_hours=_c['tz_hours'])
            tid = set_timer(crontime=_crontime,url=cron_info['url'],user_id=email,user_info=no,tz_hours=_c['tz_hours'],timerid=timerid,sem=False,save_after=True)
          
          if tid:
            tcnt += 1
            loginfo(u'  timer(No.%d) update (timerid=%s)' % (1+int(no),tid))
          else:
            cron_info['valid'] = 0
            logerr(u'  timer(No.%d) set error' % (1+int(no)))
        
        cron_info['tid'] = tid
      
      db_gc.croninfo = db.Text(simplejson.dumps(cron_info_dict))
      dbPut(db_gc)
      
      last_id = db_gc_id
      last_time = db_gc.date
    
    if max_num<=len(db_gc_list):
      str_rsp = pre_str+u'continue'
      url=PATH_RESTORE_TIMER+'?last_id=%s&last_time=%s&cnt=%d&tcnt=%d' % (urllib.quote(last_id),urllib.quote(datetime_to_isofmt(last_time)),cnt,tcnt)
      log(u'call:"%s"' % (url))
      for ci in range(3):
        try:
          taskqueue.add(url=url,method='GET',headers={'X-AppEngine-TaskRetryCount':0})
          break
        except Exception, s:
          str_rsp = pre_str+u'taskqueue error: %s' % (str(s))
          pass
        time.sleep(1)
    else:
      str_rsp = pre_str+u'end'
      log('set timer (success) number=%d' % (tcnt))
      reportServiceInfos()
      set_maintenance_mode(False)
    
    loginfo(str_rsp)
    if flg_first:
      self.redirect(req.get('return_url',PATH_TOP))
    else:
      rsp.headers['Content-Type'] = CONTENT_TYPE_PLAIN
      rsp.out.write(str_rsp)
    
  def get(self):
    self._common()
    
  def post(self):
    self._common()
  
#} // end of class restoreTimer()


#{ // class requestServiceInfo()
class requestServiceInfo(webapp.RequestHandler):
  def _common(self):
    (req,rsp,rheaders,rcookies) = common_init(self)
    load_config()
    
    nonce = req.get('nonce')
    if not nonce:
      prn_html(self,status_code=404)
      return
    
    #app_id = os.environ.get('APPLICATION_ID',u'')
    app_id = re.sub(u'^.+?~',r'',os.environ.get('APPLICATION_ID',u'')) # remove 's~' prefix
    #mail_id = str(memcache.incr(key='gaecounter',initial_value=0))
    mail_id = str(memcache.incr(key='gaecounter',initial_value=0,namespace=NAMESPACE))
    
    mail_address = 'gaecron%(mail_id)s@%(app_id)s.appspotmail.com' % dict(mail_id=mail_id,app_id=app_id)
    
    memcache.set(key=mail_address,value=nonce,time=3*60,namespace=NAMESPACE)
    
    (current_user_num,remain_user_num) = get_user_info()
    
    json = simplejson.dumps(dict(mail_address=mail_address,max_user=MAX_USER,max_timer=MAX_TIMER_PER_USER,current_user_num=current_user_num,remain_user_num=remain_user_num))
    
    rsp.headers['Content-Type'] = CONTENT_TYPE_JS
    rsp.out.write(json)
  
  #def get(self):
  #  self._common()
    
  def post(self):
    self._common()
    
#} // end of class requestServiceInfo()


#{ // class startReport()
class startReport(InboundMailHandler):
  def receive(self, message):
    """
    message: class InboundEmailMessage
      * subject contains the message subject.
      * sender is the sender's email address.
      * to is a list of the message's primary recipients.
      * cc contains a list of the cc recipients.
      * date returns the message date.
      * bodies is a list of message bodies, possibly including both plain text and HTML types.
      *   bodies = message.bodies()
      *   plaintext = message.bodies(content_type='text/plain')
      *   html = message.bodies(content_type='text/html')
      * attachments is a list of element pairs containing file types and contents.
    """
    
    (req,rsp,rheaders,rcookies) = common_init(self)
    load_config()
    
    from_address = message.sender
    to_address = message.to
    
    """
    # 管理者かどうかはこの方法では判別できなかった
    # ※app.yaml で login: admin でも、users.is_current_user_admin()がFalse。
    #   外部からアクセス出来ないだけで、内部では admin ではない(だれもログインしていない)模様。
    #
    #if not self.is_admin:
    #  logerr(u'startReport: not administrator')
    #  prn_html(self,status_code=401)
    #  return
    #
    #my_address = self.user.email()
    # 
    #if from_address != my_address:
    #  logerr(u'startReport: unmatch e-mail address(%s!=%s)' % (my_address,from_address))
    #  prn_html(self,status_code=401)
    #  return
    #
    """
    nonce = memcache.get(key=to_address,namespace=NAMESPACE)
    if nonce:
      memcache.delete(key=to_address,namespace=NAMESPACE)
    else:
      logerr(u'startReport: nonce not found')
      prn_html(self,status_code=404)
      return
    
    text = u''
    for (ctype,body) in message.bodies(content_type='text/plain'):
      text = text + unicode(body)
    text = re.sub(u'[\r\n]',r'',text)
    json = re.sub(u'^[^{]+|[^}]+$',r'',text)
    params = simplejson.loads(json)
    
    dest_nonce = params.get('nonce',u'')
    if dest_nonce != nonce:
      logerr(u'startReport: unmatch nonce(%s!=%s)' % (nonce,dest_nonce))
      prn_html(self,status_code=403)
      return
    
    dest_id = params.get('id')
    if not dest_id:
      logerr(u'startReport: id not found')
      prn_html(self,status_code=403)
      return
    
    dest_url = params.get('url')
    if not dest_url:
      logerr(u'startReport: url not found')
      prn_html(self,status_code=403)
      return
    
    if MAX_REPORT_URL<dbGaeCronReportInfo.all().count():
      logerr(u'startReport: limit over')
      prn_html(self,status_code=403)
      return
    
    club_url = re.sub(u'/[^/]+$',r'/',dest_url)
    app_id = re.sub(u'^.+?~',r'',os.environ.get('APPLICATION_ID',u'')) # remove 's~' prefix
    try:
      # from_address が管理者のものであれば、正常に送信出来る。それ以外はエラーとなる。
      mail.send_mail(
       sender = from_address,
       to = from_address,
       subject = u'GAE-Cron Report',
       body = u'Application ID "%(app_id)s" (%(app_id)s.appspot.com) 上の GAE-Cron を GAE-Cron Club\n%(club_url)s\nに登録します。\n' % dict(app_id=app_id,club_url=club_url)
       #html = json,
      )
    except Exception, s:
      logerr(u'startReport: send from %s => %s ' % (from_address,str(s)))
      prn_html(self,status_code=401)
      return
    
    db_gcr = getGaeCronReportInfo(dest_url=dest_url,dest_id=dest_id,create=True)
    if not db_gcr:
      logerr(u'startReport: cannot create data')
      prn_html(self,status_code=401)
      return
    
    (current_user_num,remain_user_num) = get_user_info()
    params = dict(
      src_id=str(db_gcr.key().id()),
      id=dest_id,
      nonce=nonce,
      authkey=db_gcr.authkey,
      max_user=MAX_USER,
      max_timer=MAX_TIMER_PER_USER,
      current_user_num=current_user_num,
      remain_user_num=remain_user_num,
    )
    log(u'call params:',params)
    log(u'report to: "%s"' % (dest_url))
    rpc = fetch_rpc(url=dest_url,method='POST',params=params,keyid=dest_url,callback=rpc_callback)
    if rpc:
      rpc.wait()
    
#} // end of class startReport()


#{ // class stopReport()
class stopReport(webapp.RequestHandler):
  def _common(self):
    (req,rsp,rheaders,rcookies) = common_init(self)
    load_config()
    
    db_id = req.get('id')
    if not db_id:
      logerr(u'stopReport: parameter error')
      prn_html(self,status_code=400)
      return
    
    db_gcr = getGaeCronReportInfo(db_id=db_id,create=False)
    if not db_gcr:
      logerr(u'stopReport: no data for id=%s' % (str(db_id)))
      prn_html(self,status_code=404)
      return
    
    authkey = req.get('authkey')
    if db_gcr.authkey != authkey:
      logerr(u'stopReport: unmatch authkey(%s!=%s)' % (db_gcr.authkey,authkey))
      prn_html(self,status_code=400)
      return
    
    log(u'### stop report: %s' % (db_gcr.dest_url))
    
    dbDelete(db_gcr)
    prn_html(self,status_code=204)
  
  #def get(self):
  #  self._common()
    
  def post(self):
    self._common()
    
#} // end of class stopReport()


#{ // def main()
def main():
  logging.getLogger().setLevel(DEBUG_LEVEL)
  
  application = webapp.WSGIApplication([
    (PATH_TOP                         , toppage           ),
    (PATH_USER_FORMAT % (u'\d+')+u'.*', userpage          ),
    (PATH_CHECK_TIMER                 , checkTimer        ),
    (PATH_RESTORE_TIMER               , restoreTimer      ),
    (PATH_REQUEST_SERV_INFO           , requestServiceInfo),
    (PATH_START_REPORT                , startReport       ),
    (PATH_STOP_REPORT                 , stopReport        ),
    (PATH_TOP+u'.*'                   , redirectToTop     ),
  ],debug=DEBUG_FLAG)
  wsgiref.handlers.CGIHandler().run(application)

#} // end of def main()


if __name__ == "__main__":
  main()

"""
#==============================================================================
# 更新履歴
#==============================================================================
2011.05.15: version 0.0.2a
 - 使用するDjangoのバージョンを明示(appengine_config.py)。
 
 - GAE_Timer()を冗長に呼んでいた箇所があったのを修正。
 
 - ユーザの登録を削除した際、タイマが残ってしまうことがある不具合の修正。
 
 - templateの文言など修正(gcc-top.html、gc-user-header.html)
 
 - appidに"s~"が付く場合があるのに対応。
   参考：http://d.hatena.ne.jp/furyu-tei/20110515/1305386911


2010.10.23: version 0.0.2
 - gaetimer.pyの仕様変更に伴う改修。
 
 - 復元用処理を gaecron.py(checkTimer) から gaetimer.py(restore) に移行。
   ※cron.yaml修正。


#------------------------------------------------------------------------------
2010.10.19: version 0.0.1f
 - version番号の修正のみ(gaetimer.pyとの整合上)


2010.06.19: version 0.0.1e
 - gaetimer.py の変更に伴う修正。
 
 - version を GAE-Cron全体と合わせ、トップページに表示するように修正。
 

2010.05.21: version 0.0.1c
 - タイマ設定／解放時に GAE_Timer 引数に namespace を指定するように修正。
   ※負荷軽減目的（セマフォ制御が namespace 毎になる）。
 
 - restoreTimer()コール用に、管理者の画面右上部に[全タイマ再設定]ボタンを追加。
   ※全登録者の有効なタイマがすべて再設定される。
     version 0.0.1b以前に設定済みのタイマを負荷分散(namespace 毎に分けて再設定)
     するため、及び、非常時の再設定用。
   ※負荷分散の処理は、一応自動的にcheckTimer()でも実施されるが、restoreTimer()
     を手動コールする方がより安全。


2010.05.07: version 0.0.1b
 - 設定画面に[試行]ボタンを追加（指定したURLが有効かどうかをその場で確認可能に)。


2010.01.18: version 0.0.1a
 - 人数が上限になると、登録済みであっても設定画面に入れなくなることがある不具合の修正。


2010.01.15: version 0.0.1
 - ソースを Web 上に公開。


2010.01.08: version -.-.-
 - 試作サービスとして公開。
   http://d.hatena.ne.jp/furyu-tei/20100108/gaecron


#------------------------------------------------------------------------------
"""
#■ end of file
