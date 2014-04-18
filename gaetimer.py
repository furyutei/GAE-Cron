# -*- coding: utf-8 -*-

"""
gaetimer.py: Timer Library and Process for Google App Engine

License: The MIT license
Copyright (c) 2010 furyu-tei
"""

__author__ = 'furyutei@gmail.com'
__version__ = '0.0.2a'

import logging,re
import time,datetime
import urllib
import wsgiref.handlers
#import hashlib

from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.api import urlfetch
from google.appengine.api import memcache
#from google.appengine.api.labs import taskqueue
from google.appengine.api.taskqueue import taskqueue
from google.appengine.api.urlfetch import InvalidURLError,DownloadError,ResponseTooLargeError
from google.appengine.api import quota

#{ // user parameters

PATH_BASE = u'/gaetimer%s'

SAVE_CALLBACK_RESULT = True   # True: save results of RPC-fetch call to memory-cache
RPC_WAIT=True                 # True: wait complete of RPC-fetch call (SAVE_CALLBACK_RESULT=True時は必ずTrueとすること)
# ※ GAEの仕様変更により、rpc.wait()しないと、callbackが呼ばれない

DEBUG_FLAG = False            # for webapp.WSGIApplication()
DEBUG_LEVEL = logging.DEBUG   # for logger
DEBUG = True                  # False: disable log() (wrapper of logging.debug())

REPORT_CPU_TIME = False       # True: report CPU Time

MAX_TIMEOUT_NUM = 20          # max number of asynchronous requests on timercycle()
MAX_CALL_NUM = 20             # max number of timercycle() called on one cycle (1 by cron.yaml, and max (MAX_CALL_NUM-1) by taskqueue())
MAX_SAVE_TIMER_PER_CYCLE = 30 # number to save db_timer per timercycle

MAX_RETRY_SEM_LOCK = 30       # max retry number of semaphore lock
INTV_RETRY_SEM_LOCK = 0.1     # wait for semaphore lock retry (sec)

DEFAULT_TZ_HOURS = +9.0       # timezone(hours) (UTC+DEFAULT_TZ_HOURS, JST=+9)
DEFAULT_DATETIME_FORMAT = '%Y/%m/%d %H:%M(JST)'
                              # 時刻表示用フォーマット

#} // end of user parameters


#{ // global variables

PATH_CYCLE           = PATH_BASE % (u'/timercycle')
PATH_SHOWLIST        = PATH_BASE % (u'/list')
PATH_SHOWLIST_SHORT  = PATH_BASE % (u'/list_short')
PATH_SHOWCOUNTER     = PATH_BASE % (u'/counter')
PATH_RESTORE         = PATH_BASE % (u'/restore')
PATH_CLEARALL        = PATH_BASE % (u'/clearall')
PATH_SET_TIMER       = PATH_BASE % (u'/settimer')
PATH_REL_TIMER       = PATH_BASE % (u'/reltimer')
PATH_DEFAULT_TIMEOUT = PATH_BASE % (u'/timeout') # for test

TIMER_NAMESPACE_BASE = 'gae_timer'
TIMER_NAMESPACE_DEFAULT = TIMER_NAMESPACE_BASE

KEY_SEM              = 'key_semaphore'
KEY_TID              = 'key_timer_id'
KEY_STATUS_BASE      = 'key_status_'
KEY_TIMEOUT_DICT     = 'key_timeout_dict'
KEY_MAINTENANCE_MODE = 'key_maintenance_mode'

CONTENT_TYPE_PLAIN  ='text/plain; charset=utf-8'

strptime = datetime.datetime.strptime
utcnow = datetime.datetime.utcnow
timedelta = datetime.timedelta

ISOFMT = '%Y-%m-%dT%H:%M:%S'

DB_FETCH_LIMIT = 100000       # max fetch number of datastore
DB_DELETE_FETCH_LIMIT = 100   # max fetch number of datastore (on delete)

#} // end of global variables


#{ // class dbGaeTimer()
class dbGaeTimer(db.Expando):
  minutes=db.IntegerProperty(default=0)
  crontime=db.StringProperty()
  tz_hours=db.FloatProperty(default=DEFAULT_TZ_HOURS)
  url=db.StringProperty()
  user_id=db.StringProperty()
  user_info=db.StringProperty()
  repeat=db.BooleanProperty(default=True)
  timeout=db.DateTimeProperty(default=None)
  flg_save=db.BooleanProperty(default=True)
  update=db.DateTimeProperty(auto_now=True)
  date=db.DateTimeProperty(auto_now_add=True)
#} // end of class dbGaeTimer()


#{ // class clMemTimer()
class clTimerKey(object):
  def __init__(self,key_name=u''):
    self.key_name=key_name
  def id_or_name(self):
    return self.key_name

class clMemTimer(object):
  def __init__(self,key_name=u'',minutes=0,crontime=u'',tz_hours=9.0,url=u'',user_id=u'',repeat=True,timeout=None,flg_save=True,update=None,date=None):
    self.key_name = key_name
    self.minutes = minutes
    self.crontime = crontime
    self.tz_hours = tz_hours
    self.url = url
    self.user_id = user_id
    self.repeat = repeat
    self.timeout = timeout
    self.flg_save = flg_save
    if update:
      self.update = update
    else:
      self.update = utcnow()
    if date:
      self.date = date
    else:
      self.date = utcnow()
  
  def key(self):
    return clTimerKey(key_name=self.key_name)
#} // end of class clMemTimer()


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
#} // end of def log()


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
#} // end of def logerr()


#{ // def get_db_timer()
def get_db_timer(timerid):
  try:
    timerid=int(timerid)
  except:
    if not isinstance(timerid,basestring):
      logerr(u'Error in get_db_timer(): invalid timerid')
      return None
  db_timer=db.get(db.Key.from_path('dbGaeTimer',timerid))
  return db_timer
#} // end of def get_db_timer()


#{ // def get_db_timerid()
def get_db_timerid(db_timer):
  try:
    timerid=str(db_timer.key().id_or_name())
  except Exception, s:
    logerr(u'Error in get_db_timerid(): cannot get timerid',s)
    return None
  return timerid
#} // end of get_db_timerid()


#{ // def datetime_to_isofmt()
def datetime_to_isofmt(t):
  try:
    return t.strftime(ISOFMT)+u'.%06d' % (t.microsecond)
  except:
    #t=utcnow()
    #return t.strftime(ISOFMT)+u'.%06d' % (t.microsecond)
    return u''
#} // end of def datetime_to_isofmt()


#{ // def isofmt_to_datetime()
def isofmt_to_datetime(isofmt):
  if not isofmt:
    return None
  try:
    elms=isofmt.split(u'.')+[u'0']
    return strptime(elms[0],ISOFMT)+timedelta(microseconds=int(elms[1]))
  except:
    #return utcnow()
    return None
#} // end of def isofmt_to_datetime()


#{ // def pack_db_timer()
re_marks=re.compile(u'(\u0000|\ufffe|\uffff)')
def _replace_mark(_str):
  if isinstance(_str,basestring):
    _str=re_marks.sub(r'',unicode(_str))
  else:
    _str=u''
  return _str

def pack_db_timer(db_timer):
  _strs=[]
  
  timer_id=get_db_timerid(db_timer)
  if not timer_id:
    timer_id=''
  _strs.append(u'%s' % (timer_id))                             #[0]
  minutes = db_timer.minutes
  if not isinstance(minutes,(int,long)):
    minutes = 0
  _strs.append(u'%d' % (minutes))                              #[1]
  tz_hours = db_timer.tz_hours
  if not isinstance(tz_hours,(int,long,float)):
    tz_hours = 9.0
  _strs.append(u'%f' % (tz_hours))                             #[2]
  _strs.append(u'%s' % (_replace_mark(db_timer.crontime)))     #[3]
  _strs.append(u'%s' % (_replace_mark(db_timer.url)))          #[4]
  _strs.append(u'%s' % (_replace_mark(db_timer.user_id)))      #[5]
  _strs.append(u'%s' % (_replace_mark(db_timer.user_info)))    #[6]
  _strs.append(u'%d' % (int(db_timer.repeat)))                 #[7]
  _strs.append(u'%d' % (int(db_timer.flg_save)))               #[8]
  _strs.append(u'%s' % (datetime_to_isofmt(db_timer.timeout))) #[9]
  _strs.append(u'%s' % (datetime_to_isofmt(db_timer.update)))  #[10]
  _strs.append(u'%s' % (datetime_to_isofmt(db_timer.date)))    #[11]
  
  db_timer_str=u'\u0000'.join(_strs)
  
  return db_timer_str
#} // enf of def pack_db_timer()


#{ // def unpack_db_timer()
def unpack_db_timer(db_timer_str):
  _strs=db_timer_str.split(u'\u0000')
  
  timer_id=str(_strs[0])
  if timer_id:
    db_timer=clMemTimer(key_name=timer_id)
  else:
    db_timer=clMemTimer()
  
  db_timer.minutes   = int(_strs[1])
  db_timer.tz_hours  = float(_strs[2])
  db_timer.crontime  = _strs[3]
  db_timer.url       = _strs[4]
  db_timer.user_id   = _strs[5]
  db_timer.user_info = _strs[6]
  db_timer.repeat    = bool(int(_strs[7]))
  db_timer.flg_save  = bool(int(_strs[8]))
  db_timer.timeout   = isofmt_to_datetime(_strs[9])
  db_timer.update    = isofmt_to_datetime(_strs[10])
  db_timer.date      = isofmt_to_datetime(_strs[11])
  
  return db_timer
#} // enf of def pack_db_timer()


#{ // def db_put()
def db_put(item,retry=2):
  for ci in range(retry):
    try:
      db.put(item)
      break
    except Exception, s:
      logerr(u'Error in db_put():',s)
      time.sleep(0.1)
#} // end of db_put()


#{ // def db_delete()
def db_delete(items,retry=2):
  for ci in range(retry):
    try:
      db.delete(items)
      break
    except Exception, s:
      logerr(u'Error in db_delete():',s)
      time.sleep(0.1)
#} // end of db_delete()


#{ // def quote_param()
def quote_param(param):
  if not isinstance(param, basestring):
    param=unicode(param)
  return urllib.quote(param.encode('utf-8'),safe='~')
#} // end of def quote_param()


#{ // def fetch_rpc()
def fetch_rpc(url,method=u'GET',headers=None,params=None,payload=None,keyid=None,callback=None):
  def handle_result(rpc):
    try:
      result=rpc.get_result()
    except InvalidURLError, s:
      callback(keyid,u'InvalidURLError')
      return
    except DownloadError, s:
      callback(keyid,u'DownloadError')
      return
    except ResponseTooLargeError, s:
      callback(keyid,u'ResponseTooLargeError')
      return
    except Exception, s:
      callback(keyid,s)
      return
    callback(keyid,result)
  
  if not headers: headers={}
  if not headers.has_key('Cache-Control'): headers['Cache-Control']='no-cache,max-age=0'
  
  if not payload and params:
    pairs=[]
    for key in sorted(params.keys()):
      pairs.append(u'%s=%s' % (quote_param(key),quote_param(params[key])))
    payload=u'&'.join(pairs)
  
  if payload:
    if method=='POST':
      headers['Content-Type']='application/x-www-form-urlencoded'
    else:
      url=u'%s?%s' % (url,payload)
      payload=None
  
  try:
    url=str(url)
  except Exception, s:
    logerr(u'Error in fetch_rpc(): invalid URL "%s"' % (url),s)
    if callback:
      callback(keyid,u'URL error')
    return None
  
  rpc=urlfetch.create_rpc(deadline=10)
  if callback:
    rpc.callback=lambda:handle_result(rpc)
  
  urlfetch.make_fetch_call(rpc=rpc, url=url, method=method, headers=headers, payload=payload)
  
  return rpc
#} // end of def fetch_rpc()


#{ // def cron_getrange()
re_asta_sla=re.compile(u'^\*/(\d+)$')
re_hyphen=re.compile(u'^(\d+)-(\d+)')
def cron_getrange(field,min,max):
  if field=='*':
    return range(min,1+max)
  mrslt=re_asta_sla.search(field)
  if mrslt:
    _step=int(mrslt.group(1))
    if 0<_step:
      return range(min,1+max,_step)
    else:
      return []
  
  def _getrange(elm):
    mrslt=re_hyphen.search(elm)
    if not mrslt:
      try:
        return [int(elm)]
      except:
        return []
    
    (n1,n2)=(int(mrslt.group(1)),int(mrslt.group(2)))
    if (n1<min or max<n1) or (n2<min or max<n2):
      return []
    if n1<n2:
      return range(n1,1+n2)
    else:
      return range(min,1+n2)+range(n1,1+max)
  
  rn=set()
  for elm in field.split(','):
    rn.update(_getrange(elm))
  
  rn=sorted(rn)
  if 0<len(rn):
    if rn[0]<min or max<rn[-1]:
      return []
  
  return rn
#} // end of def cron_getrange()


#{ // def cron_nexttime()
re_chop_space=re.compile(u'^\s+|\s+$')
re_space=re.compile(u'\s+')
def cron_nexttime(crontime,tz_hours=DEFAULT_TZ_HOURS,lasttime=None):
  if not isinstance(crontime,basestring): return None
  
  fs=re_space.split(re_chop_space.sub(r'',crontime))
  if len(fs)!=5: return None
  
  rmin=cron_getrange(fs[0],0,59)
  if len(rmin)<=0: return None
  
  rhour=cron_getrange(fs[1],0,23)
  if len(rhour)<=0: return None
  
  rday=cron_getrange(fs[2],1,31)
  if len(rday)<=0: return None
  
  rmonth=cron_getrange(fs[3],1,12)
  if len(rmonth)<=0: return None
  
  rwday=cron_getrange(fs[4],0,7)
  if len(rwday)<=0: return None
  # 0(Sunday) => 7(Sunday) for isoweekday()
  if rwday[0] == 0:
    rwday.pop(0)
    if len(rwday)==0 or rwday[-1] != 7:
      rwday.append(7)
  
  if not lasttime:
    lasttime=utcnow()
  
  dt=lasttime+timedelta(hours=tz_hours)
  
  tmin=dt.minute
  dmin=None
  for _min in rmin:
    if tmin < _min:
      dmin=_min-tmin
      break
  if dmin == None:
    dmin=60+rmin[0]-tmin
  
  dt=dt+timedelta(minutes=dmin)
  
  thour=dt.hour
  dhour=None
  for _hour in rhour:
    if thour <= _hour:
      dhour=_hour-thour
      break
  if dhour == None:
    dhour=24+rhour[0]-thour
  
  dt=dt+timedelta(hours=dhour)
  
  day_or_wday=False
  if fs[2]!='*' and fs[4]!='*':
    day_or_wday=True
  for ci in range(366):
    (tmonth,tday,twday)=(dt.month,dt.day,dt.isoweekday())
    if tmonth in rmonth:
      if day_or_wday and ((tday in rday) or (twday in rwday)):
        break
      elif (tday in rday) and (twday in rwday):
        break
    dt=dt+timedelta(days=1)
  
  if 365<=ci:
    return None
  
  dt=dt-timedelta(hours=tz_hours,seconds=dt.second,microseconds=dt.microsecond)
  
  return dt
#} // end of def cron_nexttime()


#{ // class SemaphoreError()
class SemaphoreError(Exception):
  def __init__(self,value):
    self.value=value
  
  def __str__(self):
    return self.value
#} // end of class SemaphoreError()


#{ // class GAE_Timer()
class GAE_Timer(object):
  def __init__(self,init=None,namespace=TIMER_NAMESPACE_DEFAULT,def_timeout_path=PATH_DEFAULT_TIMEOUT,ignore_duplicate=True):
    self.namespace=namespace
    self.def_timeout_path=def_timeout_path
    self._timer_init()
    self.curtime=utcnow()
    self.snap_timeout_dict=None
  
  def get_timer_namespace_by_string(self,base_str):
    return self.namespace # dummy
  
  def get_timer_namespace_by_number(self,base_num):
    return self.namespace # dummy
  
  def _sem_init(self):
    memcache.delete(key=KEY_SEM,namespace=self.namespace)
    loginfo('init semaphore (namespace=%s)' % (self.namespace))
  
  def _sem_lock(self):
    try:
      _num=memcache.incr(key=KEY_SEM,initial_value=0,namespace=self.namespace)
      if _num == 1:
        #log('_sem_lock: success (namespace=%s)' % (self.namespace))
        return True
      else:
        memcache.decr(key=KEY_SEM,namespace=self.namespace)
        log('_sem_lock: failure (number=%s) (namespace=%s)' % (str(_num),self.namespace))
        return False
    except Exception, s:
      logerr('Error in GAE_Timer()._sem_lock():',s)
      return False
  
  def _sem_lock_retry(self,retry_num=MAX_RETRY_SEM_LOCK):
    for ci in range(1+retry_num):
      if self._sem_lock():
        if 0<ci:
          log('get semaphore: retry number=%d (namespace=%s)' % (ci,self.namespace))
        return True
      if ci<=retry_num:
        time.sleep(INTV_RETRY_SEM_LOCK)
      else:
        break
    raise SemaphoreError('_sem_lock_retry: semaphore lock timeout')
  
  def _sem_unlock(self):
    try:
      _num=memcache.decr(key=KEY_SEM,namespace=self.namespace)
      if _num == 0:
        #log('_sem_unlock: success (namespace=%s)' % (self.namespace))
        pass
      else:
        log('_sem_unlock: success (namespace=%s) remain number=%s (temporary conflict with others)' % (self.namespace,str(_num)))
    except Exception, s:
      logerr('Error in GAE_Timer()._sem_unlock():',s)
  
  def _timer_init(self):
    pass # dummy
  
  def _get_timerid(self):
    return str(memcache.incr(key=KEY_TID,initial_value=0,namespace=self.namespace))
  
  def get_timer_namespace(self):
    return self.namespace
  
  def get_def_timeout_path(self):
    return self.def_timeout_path
  
  def clear_all_timers(self):
    log(u'GAE_Timer().clear_all_timers(): start')
    
    self._sem_init()
    flg_sem=self._sem_lock()
    
    memcache.delete(key=KEY_TIMEOUT_DICT,namespace=self.namespace)
    
    db_timer_all=dbGaeTimer.all()
    while True:
      db_timer_list=db_timer_all.fetch(DB_DELETE_FETCH_LIMIT)
      len_list=len(db_timer_list)
      if len_list<=0:
        break
      db_delete(db_timer_list)
      if len_list<DB_DELETE_FETCH_LIMIT:
        break
    
    if flg_sem:
      self._sem_unlock()
    
    log(u'GAE_Timer().clear_all_timers(): normal end')
  
  def set_timer(self,minutes=None,crontime=None,tz_hours=DEFAULT_TZ_HOURS,url=None,user_id=None,user_info=None,repeat=True,timerid=None,sem=True,save_after=False,prn=False,tvalue=None):
    log(u'GAE_Timer().set_timer(): start')
    
    try:
      url=str(url)
    except Exception, s:
      logerr(u'Error in GAE_Timer().set_timer(): invalid URL "%s"' % (url),s)
      return None
    
    if timerid:
      if save_after:
        #db_timer=dbGaeTimer(key_name=str(timerid))
        db_timer=clMemTimer(key_name=str(timerid))
      else:
        db_timer=get_db_timer(timerid)
        if not db_timer:
          #logerr(u'Error in GAE_Timer().set_timer(): existing timer not found(timerid=%s)' % str(timerid))
          #return None
          db_timer=dbGaeTimer(key_name=str(timerid))
    else:
      db_timer=dbGaeTimer()
    
    if crontime:
      timeout=cron_nexttime(crontime,tz_hours=tz_hours,lasttime=self.curtime)
      if not timeout:
        logerr(u'Error in GAE_Timer().set_timer(): invalid cron format',crontime)
        return None
    else:
      if not isinstance(minutes,(int,long)) or minutes<1:
        logerr(u'Error in GAE_Timer().set_timer(): invalid timeout minutes',minutes)
        return None
      timeout=self.curtime+timedelta(minutes=minutes)
    
    db_timer.minutes=minutes
    db_timer.crontime=crontime
    db_timer.tz_hours=tz_hours
    db_timer.url=url
    db_timer.user_id=user_id
    db_timer.user_info=user_info
    db_timer.repeat=repeat
    db_timer.timeout=timeout
    
    if save_after:
      loginfo(u'save after: timer(timerid=%s)' % str(timerid))
      db_timer.flg_save=False
    else:
      db_put(db_timer)
    
    if not timerid:
      timerid=get_db_timerid(db_timer)
    
    if sem:
      try:
        flg_sem=self._sem_lock_retry()
      except Exception, s:
        logerr(u'Error in GAE_Timer().set_timer(): semaphore lock failure',s)
        return None
    
    try:
      #timeout_dict=memcache.get(key=KEY_TIMEOUT_DICT,namespace=self.namespace)
      timeout_dict=self.get_timeout_dict()
      timeout_dict[timerid]=db_timer
      #memcache.set(key=KEY_TIMEOUT_DICT,value=timeout_dict,time=0,namespace=self.namespace)
      self.set_timeout_dict(timeout_dict)
    except Exception, s:
      logerr(u'Error in GAE_Timer().set_timer(): cannot load or save timeout_dict',s)
    
    if sem and flg_sem:
      self._sem_unlock()
    
    log(u'GAE_Timer().set_timer(): normal end')
    return timerid
  
  def rel_timer(self,timerid,sem=True,prn=False):
    log(u'GAE_Timer().rel_timer(): start')
    
    if sem:
      try:
        flg_sem=self._sem_lock_retry()
      except Exception, s:
        logerr(u'Error in GAE_Timer().rel_timer(): semaphore lock failure',s)
        return None
    
    try:
      #timeout_dict=memcache.get(key=KEY_TIMEOUT_DICT,namespace=self.namespace)
      timeout_dict=self.get_timeout_dict()
      if timeout_dict.has_key(timerid):
        del(timeout_dict[timerid])
      #memcache.set(key=KEY_TIMEOUT_DICT,value=timeout_dict,time=0,namespace=self.namespace)
      self.set_timeout_dict(timeout_dict)
    except Exception, s:
      logerr(u'Error in GAE_Timer().rel_timer(): cannot load or save timeout_dict',s)
    
    if sem and flg_sem:
      self._sem_unlock()
    
    db_timer=get_db_timer(timerid)
    if not db_timer:
      logerr(u'Error in GAE_Timer().rel_timer(): existing timer not found(timerid=%s)' % str(timerid))
      return None
    
    db_delete(db_timer)
    
    log(u'GAE_Timer().rel_timer(): normal end')
    return
  
  def get_timeout_list(self,max_num=0):
    log('GAE_Timer().get_timeout_list(): start')
    
    try:
      flg_sem=self._sem_lock_retry()
    except Exception, s:
      logerr(u'Error in GAE_Timer().get_timeout_list(): semaphore lock failure (patter-A)',s)
      self._sem_init()
      try:
        flg_sem=self._sem_lock_retry()
      except Exception, s:
        logerr(u'Error in GAE_Timer().get_timeout_list(): semaphore lock failure (pattern-B)',s)
        flg_sem=None
    
    try:
      #timeout_dict=memcache.get(key=KEY_TIMEOUT_DICT,namespace=self.namespace)
      timeout_dict=self.get_timeout_dict()
    except Exception, s:
      logerr(u'Error in GAE_Timer().get_timeout_list(): cannot load timeout_dict',s)
      timeout_dict={}
    
    (db_timeout_entries,flg_remain,cnt_entry)=([],False,0)
    curtime=self.curtime
    
    cnt_save=MAX_SAVE_TIMER_PER_CYCLE
    for (timerid,db_timer) in timeout_dict.items():
      flg_next=False
      timeout=db_timer.timeout
      if timeout:
        while not flg_remain:
          if curtime<timeout:
            break
          if max_num<=cnt_entry:
            flg_remain=True
            break
          cnt_entry+=1
          db_timeout_entries.append(db_timer)
          if db_timer.repeat:
            flg_next=True
          else:
            db_timer.timeout=datetime.datetime(datetime.MAXYEAR,1,1,0,0,0,0)
          break
      else:
        flg_next=True
      
      if flg_next:
        if db_timer.crontime:
          next_timeout=cron_nexttime(db_timer.crontime,tz_hours=db_timer.tz_hours,lasttime=curtime)
        elif isinstance(db_timer.minutes,(int,long)) and 0<db_timer.minutes:
          next_timeout=curtime+timedelta(minutes=db_timer.minutes)
        else:
          next_timeout=None
        db_timer.timeout=next_timeout
    
      if not db_timer.flg_save and 0<cnt_save:
        loginfo(u'save timer(timerid=%s)' % get_db_timerid(db_timer))
        #db_timer.flg_save=True
        #db_put(db_timer)
        db_put(dbGaeTimer(
          key_name = db_timer.key_name,
          minutes = db_timer.minutes,
          crontime = db_timer.crontime,
          tz_hours = db_timer.tz_hours,
          url = db_timer.url,
          user_id = db_timer.user_id,
          user_info = db_timer.user_info,
          repeat = db_timer.repeat,
          timeout = db_timer.timeout,
          flg_save = db_timer.flg_save,
        ))
        db_timer.flg_save=True
        cnt_save-=1
    
    try:
      #memcache.set(key=KEY_TIMEOUT_DICT,value=timeout_dict,time=0,namespace=self.namespace)
      self.set_timeout_dict(timeout_dict)
    except Exception, s:
      logerr(u'Error in GAE_Timer().get_timeout_list(): cannot save timeout_dict',s)
    
    if flg_sem:
      self._sem_unlock()
    
    log('GAE_Timer().get_timeout_list(): normal end')
    return (db_timeout_entries,flg_remain)
  
  def check_and_restore(self):
    log('GAE_Timer().check_and_restore(): start')
    
    if get_maintenance_mode():
      loginfo(u'*** maintenance mode ***')
      return
    
    try:
      flg_sem=self._sem_lock_retry()
    except Exception, s:
      logerr(u'Error in GAE_Timer().check_and_restore(): semaphore lock failure (pattern-A)',s)
      self._sem_init()
      try:
        flg_sem=self._sem_lock_retry()
      except Exception, s:
        logerr(u'Error in GAE_Timer().check_and_restore(): semaphore lock failure (pattern-B)',s)
        flg_sem=None
    
    try:
      #timeout_dict=memcache.get(key=KEY_TIMEOUT_DICT,namespace=self.namespace)
      timeout_dict=self.get_timeout_dict()
    except Exception, s:
      logerr(u'Error in GAE_Timer().check_and_restore(): cannot load timeout_dict',s)
      timeout_dict={}
    
    curtime=self.curtime
    db_timers=dbGaeTimer.all()
    
    for db_timer in db_timers:
      timerid=get_db_timerid(db_timer)
      if not timerid:
        continue
      if timeout_dict.has_key(timerid):
        continue
      loginfo(u'timer(timerid=%s) not exist in cache' % str(timerid))
      if not db_timer.timeout:
        if db_timer.crontime:
          next_timeout=cron_nexttime(db_timer.crontime,tz_hours=db_timer.tz_hours,lasttime=curtime)
        elif isinstance(db_timer.minutes,(int,long)) and 0<db_timer.minutes:
          next_timeout=curtime+timedelta(minutes=db_timer.minutes)
        else:
          next_timeout=None
        db_timer.timeout=next_timeout
      timeout_dict[timerid]=db_timer
    
    try:
      #memcache.set(key=KEY_TIMEOUT_DICT,value=timeout_dict,time=0,namespace=self.namespace)
      self.set_timeout_dict(timeout_dict)
    except Exception, s:
      logerr(u'Error in GAE_Timer().check_and_restore(): cannot save timeout_dict',s)
    
    if flg_sem:
      self._sem_unlock()
    
    log('GAE_Timer().check_and_restore(): normal end')
  
  def prn_timer_header(self,header=None):
    pass # dummy
  
  def prn_timer(self,timer_map=None,timerid=None,db_timer=None):
    if timerid:
      db_timer=get_db_timer(timerid)
    elif db_timer:
      timerid=get_db_timerid(db_timer)
    if not db_timer:
      return
    
    tmems=['minutes','crontime','tz_hours','url','user_id','user_info','repeat']
    log(u' [timer(id=%s)]' % str(timerid))
    for mem in tmems:
      log(u'  %s = %s' % (mem,str(getattr(db_timer,mem,u''))))
    log('')
  
  def prn_timer_short(self,timer_map=None,timerid=None,db_timer=None):
    if timerid:
      db_timer=get_db_timer(timerid)
    elif db_timer:
      timerid=get_db_timerid(db_timer)
    if not db_timer:
      return
    
    tmems=['url','user_id','user_info']
    log(u' [timer(id=%s)]' % str(timerid))
    for mem in tmems:
      log(u'  %s = %s' % (mem,str(getattr(db_timer,mem,u''))))
    log('')
  
  def prn_tim_list(self,header=None,timer_map=None,sem=True):
    try:
      db_timers=dbGaeTimer.all().order('update')
    except Exception, s:
      logerr(u'Error in GAE_Timer().prn_tim_list(): cannot get timer list',s)
      db_timers=[]
    
    for db_timer in db_timers:
      self.prn_timer(db_timer=db_timer)
    
  def prn_tim_list_short(self,header=None,timer_map=None,sem=True):
    try:
      db_timers=dbGaeTimer.all().order('update')
    except Exception, s:
      logerr(u'Error in GAE_Timer().prn_tim_list_short(): cannot get timer list',s)
      db_timers=[]
    
    for db_timer in db_timers:
      self.prn_timer_short(db_timer=db_timer)
  
  def get_tim_counter(self,header=None,timer_map=None,sem=True):
    cnt=rcnt=dbGaeTimer.all().count()
    return (header,cnt,rcnt)
  
  def prn_tim_counter(self):
    (header,cnt,rcnt)=self.get_tim_counter()
    
    self.prn_timer_header(header)
    log(u'count=%d (reverse=%d)' % (cnt,rcnt))
  
  def set_timeout_dict(self,timeout_dict):
    if REPORT_CPU_TIME: cpu_start = quota.get_request_cpu_usage()
    #memcache.set(key=KEY_TIMEOUT_DICT,value=timeout_dict,time=0,namespace=self.namespace)
    _list=timeout_dict.items()
    timeout_dict_str=u'\uffff'.join([u'%s\ufffe%s' % (timerid,pack_db_timer(db_timer)) for (timerid,db_timer) in _list])
    memcache.set(key=KEY_TIMEOUT_DICT,value=timeout_dict_str,time=0,namespace=self.namespace)
    log(u'GAE_Timer().set_timeout_dict(): total number of timers=%d' % (len(_list)))
    if REPORT_CPU_TIME: cpu_end = quota.get_request_cpu_usage()
    if REPORT_CPU_TIME: log(u'set_timeout_dict()_string: %d megacycles' % (cpu_end-cpu_start))
  
  def get_timeout_dict(self):
    if REPORT_CPU_TIME: cpu_start = quota.get_request_cpu_usage()
    timeout_dict_str = memcache.get(key=KEY_TIMEOUT_DICT,namespace=self.namespace)
    if isinstance(timeout_dict_str,dict):
      timeout_dict=timeout_dict_str
    elif not timeout_dict_str:
      timeout_dict={}
    else:
      """
      #timeout_dict={}
      #for _str in timeout_dict_str.split(u'\uffff'):
      #  (timerid,db_timer_str) = _str.split(u'\ufffe')
      #  timeout_dict[str(timerid)]=unpack_db_timer(db_timer_str)
      """
      def list_to_dict(src_list):
        def pairwise(iterable):
          itnext = iter(iterable).next
          while True:
            yield itnext(),unpack_db_timer(itnext())
        return dict(pairwise(src_list))
      _list=re.split(u'\uffff|\ufffe',timeout_dict_str)
      log(u'GAE_Timer().get_timeout_dict(): total number of timers=%d' % (len(_list)/2))
      timeout_dict=list_to_dict(_list)
    if not timeout_dict:
      timeout_dict={}
    if REPORT_CPU_TIME: cpu_end = quota.get_request_cpu_usage()
    if REPORT_CPU_TIME: log(u'get_timeout_dict(): %d megacycles' % (cpu_end-cpu_start))
    return timeout_dict
  
  def set_last_status(self,timerid,last_timeout=u'',last_result=u''):
    if REPORT_CPU_TIME: cpu_start = quota.get_request_cpu_usage()
    #memcache.set(key=KEY_STATUS_BASE+str(timerid),value=dict(last_timeout=last_timeout,last_result=last_result),time=0,namespace=self.namespace)
    memcache.set(key=KEY_STATUS_BASE+str(timerid),value=u'%s\u0000%s' % (last_timeout,last_result),time=0,namespace=self.namespace)
    if REPORT_CPU_TIME: cpu_end = quota.get_request_cpu_usage()
    if REPORT_CPU_TIME: log(u'set_last_status(): %d megacycles' % (cpu_end-cpu_start))
  
  def get_last_status(self,timerid):
    if REPORT_CPU_TIME: cpu_start = quota.get_request_cpu_usage()
    last_status_str=memcache.get(key=KEY_STATUS_BASE+str(timerid),namespace=self.namespace)
    if isinstance(last_status_str,basestring):
      (last_timeout,last_result)=last_status_str.split(u'\u0000')
      last_status = dict(last_timeout=last_timeout,last_result=last_result)
    else:
      last_status = last_status_str
    if not last_status:
      last_status=dict(last_timeout=u'',last_result=u'')
    if REPORT_CPU_TIME: cpu_end = quota.get_request_cpu_usage()
    if REPORT_CPU_TIME: log(u'get_last_status(): %d megacycles' % (cpu_end-cpu_start))
    return last_status

  def get_next_time(self,timerid,fmt=DEFAULT_DATETIME_FORMAT,use_snapshot=True):
    if use_snapshot and self.snap_timeout_dict:
      timeout_dict=self.snap_timeout_dict
    else:
      try:
        #timeout_dict=memcache.get(key=KEY_TIMEOUT_DICT,namespace=self.namespace)
        timeout_dict=self.get_timeout_dict()
      except Exception, s:
        logerr(u'Error in GAE_Timer().get_next_time(): cannot load timeout_dict',s)
        timeout_dict={}
      self.snap_timeout_dict=timeout_dict
    
    db_timer=timeout_dict.get(timerid)
    if not db_timer:
      logerr(u'Error in GAE_Timer().get_next_time(): timer not found: id=%s' % (str(timerid)))
      return u''
    if not db_timer.timeout:
      log(u'GAE_Timer().get_next_time(): empty timeout parameter: id=%s' % (str(timerid)))
      return u''
    return (db_timer.timeout+timedelta(hours=DEFAULT_TZ_HOURS)).strftime(fmt)
  
  def get_timer_map(self):
    return [] # dummy
  
#} // end of class GAE_Timer()


#{ // def timer_maintenance()
def timer_maintenance():
  gae_timer=GAE_Timer()
  gae_timer.check_and_restore()

#} // end of def timer_maintenance()


#{ // def timer_initialize()
def timer_initialize():
  gae_timer=GAE_Timer()
  gae_timer.clear_all_timers()
  
#} // end of def timer_initialize()


#{ // def prn_timer_headers()
def prn_timer_headers():
  gae_timer=GAE_Timer()
  gae_timer.prn_timer_header()
  
#} // end of def prn_timer_headers()


#{ // def get_maintenance_mode()
def get_maintenance_mode():
  try:
    flg=memcache.get(key=KEY_MAINTENANCE_MODE,namespace=TIMER_NAMESPACE_DEFAULT)
  except:
    flg=False
  if flg:
    maintenance_mode=True
    log(u'*** maintenance_mode = ON  ***')
  else:
    maintenance_mode=False
    log(u'*** maintenance_mode = OFF ***')
  return maintenance_mode
#} // end of def get_maintenance_mode()


#{ // def set_maintenance_mode()
def set_maintenance_mode(flg=False):
  if flg:
    maintenance_mode=True
    loginfo(u'*** set maintenance_mode flag ***')
  else:
    maintenance_mode=False
    loginfo(u'*** reset maintenance_mode flag ***')
  try:
    memcache.set(key=KEY_MAINTENANCE_MODE,value=maintenance_mode,time=0,namespace=TIMER_NAMESPACE_DEFAULT)
  except:
    pass
  return maintenance_mode
#} // end of set_maintenance_mode()


#{ // class timercycle()
re_def_url=re.compile(u'^([^:]+://[^/]*).*$')

class timercycle(webapp.RequestHandler):
  def get(self):
    (req,rsp)=(self.request,self.response)
    
    rsp.set_status(200)
    str_rsp=u'complete'
    
    while True:
      if get_maintenance_mode():
        loginfo(u'*** maintenance mode ***')
        str_rsp=u'maintenance mode'
        break
      
      try:
        call_num=int(req.get('num','1'))
      except:
        call_num=1
      
      gae_timer=GAE_Timer()
      curtime_str=(gae_timer.curtime+timedelta(hours=DEFAULT_TZ_HOURS)).strftime(DEFAULT_DATETIME_FORMAT)
      
      log(u'timercycle().get(): %s (call number=%d)' % (curtime_str,call_num))
      
      (db_timeout_entries,flg_remain)=gae_timer.get_timeout_list(max_num=MAX_TIMEOUT_NUM)
      
      log(u'  number of timeout entries: %d' % (len(db_timeout_entries)))
      
      urls={}
      def callback(timerid,result):
        log(u'callback(timerid=%s): "%s"' % (str(timerid),urls[timerid]))
        if isinstance(result,basestring):
          s_result=result
        elif result:
          try:
            s_result=u'code: %d' % (result.status_code)
          except:
            try:
              s_result=unicode(result)
            except:
              s_result=u'unknown error(1)'
        else:
          s_result=u'unknown error(2)'
        gae_timer.set_last_status(timerid=timerid,last_timeout=curtime_str,last_result=s_result)
        log(s_result)
      
      def_url=re_def_url.sub(r'\1',req.url)+gae_timer.get_def_timeout_path()
      
      while flg_remain:
        call_num+=1
        if MAX_CALL_NUM < call_num:
          str_rsp=u'stop(max number(%d) called)' % (MAX_CALL_NUM)
          break
        _url=PATH_CYCLE+'?num=%d' % (call_num)
        log('  timeout timers left => call taskqueue (%s)' % (_url))
        try:
          taskqueue.add(url=_url,method='GET',headers={'X-AppEngine-TaskRetryCount':0})
          str_rsp=u'continue'
          break
        except Exception, s:
          logerr('Error in timercycle().get(): cannot add taskqueue',s)
          pass
        break
      
      log(u'=====')
      rpcs=[]
      for db_timer in db_timeout_entries:
        timerid=get_db_timerid(db_timer)
        if not timerid:
          continue
        gae_timer.prn_timer_short(db_timer=db_timer)
        url=db_timer.url
        if url:
          params=None
        else:
          url=def_url
          params={'timerid':timerid}
          if db_timer.user_id is not None:
            params['user_id']=db_timer.user_id
          if db_timer.user_info is not None:
            params['user_info']=db_timer.user_info
        
        urls[timerid]=url
        log(u'call(timerid=%s): "%s"' % (timerid,url))
        log(u'-----')
        
        if SAVE_CALLBACK_RESULT:
          rpc=fetch_rpc(url=url,method='GET',params=params,keyid=timerid,callback=callback)
        else:
          rpc=fetch_rpc(url=url,method='GET',params=params,keyid=timerid)
        if rpc:
          rpcs.append(rpc)
      
      if RPC_WAIT:
        for rpc in rpcs:
          rpc.wait()
       
      break
    
    log(u'timercycle().get(): %s' % str_rsp)
    rsp.headers['Content-Type']=CONTENT_TYPE_PLAIN
    rsp.out.write(str_rsp)

#} // end of class timercycle()


#{ // class showlist()
class showlist(webapp.RequestHandler):
  def get(self):
    (req,rsp)=(self.request,self.response)
    
    gae_timer=GAE_Timer()
    gae_timer.prn_tim_list()

    rsp.headers['Content-Type']=CONTENT_TYPE_PLAIN
    rsp.out.write('normal end')
    
#} // end of class showlist()


#{ // class showlist_short()
class showlist_short(webapp.RequestHandler):
  def get(self):
    (req,rsp)=(self.request,self.response)
    
    gae_timer=GAE_Timer()
    gae_timer.prn_tim_list_short()

    rsp.headers['Content-Type']=CONTENT_TYPE_PLAIN
    rsp.out.write('normal end')
    
#} // end of class showlist_short()


#{ // class showcounter()
class showcounter(webapp.RequestHandler):
  def get(self):
    (req,rsp)=(self.request,self.response)
    
    gae_timer=GAE_Timer()
    gae_timer.prn_tim_counter()

    rsp.headers['Content-Type']=CONTENT_TYPE_PLAIN
    rsp.out.write('normal end')
    
#} // end of class showcounter()


#{ // class restore()
class restore(webapp.RequestHandler):
  def get(self):
    (req,rsp)=(self.request,self.response)
    
    gae_timer=GAE_Timer()
    gae_timer.check_and_restore()
    
    rsp.headers['Content-Type']=CONTENT_TYPE_PLAIN
    rsp.out.write('normal end')

#} // end of class restore()


#{ // class clearall()
class clearall(webapp.RequestHandler):
  def _common(self):
    (req,rsp)=(self.request,self.response)
    
    gae_timer=GAE_Timer()
    gae_timer.clear_all_timers()
    gae_timer.prn_timer_header()
  
    rsp.headers['Content-Type']=CONTENT_TYPE_PLAIN
    rsp.out.write('normal end')
    
  def get(self):
    self._common()
  
  def post(self):
    self._common()

#} // end of class clearall()


#{ // class def_timeout()
class def_timeout(webapp.RequestHandler):
  def get(self):
    (req,rsp)=(self.request,self.response)
    (rheaders,rcookies)=(req.headers,req.cookies)
    
    rsp.set_status(200)
    log(u'def_timeout: called')
    
    log(u'["%s" called]' % (req.uri))
    log(u' IP Address: "%s"' % (req.remote_addr))
    log(u' Referer   : "%s"' % (rheaders.get('Referer',u'')))
    log(u' User-Agent: "%s"' % (rheaders.get('User-Agent',u'')))
    
    log(u'def_timeout: end')
    rsp.out.write('def_timeout: end')

#} // end of class def_timeout()


#{ // class settimer()
class settimer(webapp.RequestHandler):
  def _common(self):
    (req,rsp)=(self.request,self.response)
    (rheaders,rcookies)=(req.headers,req.cookies)
    
    gae_timer=GAE_Timer()
    try:
      minutes=int(req.get('minutes'))
    except:
      minutes=None
    try:
      tz_hours=float(req.get('tz_hours',DEFAULT_TZ_HOURS))
    except:
      tz_hours=DEFAULT_TZ_HOURS
    if req.get('repeat')=='1':
      repeat=True
    else:
      repeat=False
    
    timerid=gae_timer.set_timer(
      minutes=minutes,
      crontime=req.get('crontime'),
      tz_hours=tz_hours,
      url=req.get('url'),
      user_id=req.get('user_id'),
      user_info=req.get('user_info'),
      repeat=repeat,
      timerid=req.get('timer_id'),
    )
    rsp.set_status(200)
    rsp.headers['Content-Type']=CONTENT_TYPE_PLAIN
    if timerid:
      timerid=str(timerid)
    else:
      timerid=u''
    rsp.out.write(timerid)
  
  def get(self):
    self._common()

  def post(self):
    self._common()

#} // end of class settimer()


#{ // class reltimer()
class reltimer(webapp.RequestHandler):
  def _common(self):
    (req,rsp)=(self.request,self.response)
    (rheaders,rcookies)=(req.headers,req.cookies)
    
    gae_timer=GAE_Timer()
    gae_timer.rel_timer(
      timerid=req.get('timerid'),
    )
    rsp.set_status(200)
    rsp.headers['Content-Type']=CONTENT_TYPE_PLAIN
    rsp.out.write(u'')

  def get(self):
    self._common()

  def post(self):
    self._common()

#} // end of class reltimer()


#{ // def main()
def main():
  logging.getLogger().setLevel(DEBUG_LEVEL)
  application=webapp.WSGIApplication([
    (PATH_CYCLE          , timercycle    ),
    (PATH_SHOWLIST       , showlist      ),
    (PATH_SHOWLIST_SHORT , showlist_short),
    (PATH_SHOWCOUNTER    , showcounter   ),
    (PATH_RESTORE        , restore       ),
    (PATH_CLEARALL       , clearall      ),
    (PATH_SET_TIMER      , settimer      ),
    (PATH_REL_TIMER      , reltimer      ),
    (PATH_DEFAULT_TIMEOUT, def_timeout   ),
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
 - パフォーマンス改善のため、memcacheアクセスで、
     書き込み時：object/dictからunicode文字列に変換
     読み出し時：unicode文字列からobject/dictへの変換
   を行なうように改修。
   ※object/dictの読み書きはunicodeの場合と比較してオーバヘッドが大きい。
     (object/dict←→unicode変換処理の効率が良い場合、パフォーマンス改善になる)
     参考：http://d.hatena.ne.jp/furyu-tei/20110511/1305123378
   ※GAE_Timer()下のset_timeout_dict()、get_timeout_dict()、set_last_status()、
     get_last_status()が対象。
   ※db.Expandoはobject作成時の負荷が高いため、memcacheアクセス用に、別途
     clMemTimerを用意。


2010.10.23: version 0.0.2
 - タイマ用の元データをmemcache上に持つのを止め、datastore上に持つように全面改修。
   ※memcacheは前振れなく消えることがあり、データの不整合が発生しやすいため、
     datastoreの情報から復元できるようにした。
 
 - 復元用処理を gaecron.py(checkTimer) から gaetimer.py(restore) に移行。
   ※cron.yaml修正。


#------------------------------------------------------------------------------
2010.10.19: version 0.0.1f
 - 前回実行時刻と結果が表示されないようになっていたのを修正。
   ※GAEの仕様変更のため(?)、rpc.wait()を明示的にコールしないとcallbackされない
     ようになった模様（callback中で前回時刻等を記録していた)。
 
 - タイマの一部がうまく実行されないことがある不具合修正。


2010.06.21: version 0.0.1e1
 - version 0.01eにて、誤って_sem_init()の中身が空にしていたのを修正。
 

2010.06.19: version 0.0.1e
 - タイマキューを同時タイムアウト対応にした class GAE_Timer2nd() 追加。
   ※旧来の class GAE_Timer() は class GAE_Timer1st() に変更。
     def GAE_Timer() を新設し、namespace で内部的に区別。
 
 - GAE_Timer2nd の timercycle処理（本体は get_timeout_list()）を見直し、特に 
   _reset_timer() と set_timer() 処理を改修し、パフォーマンス改善。
 
 - その他、各種不具合対応。
 

2010.05.21: version 0.0.1d
 - 修復処理（check_and_restore()）で、まれに timercycle処理が割り込み、_reset_timer()
   （から呼ぶset_timer()）処理で例外が発生、データが消えてしまう現象への対策。
 
 - timercycle()で、nsidオプション(1～MAX_TIMER_TASK_NUMBER)を付けたものを
   cron.yamlによる設定ではなく、内部で直接コールするように修正。
   ※これにより、常に gae_timer(デフォルト)、及び 1～MAX_TIMER_TASK_NUMBER が添付
     された namespace をもつタイマキューが並列処理されるようになった。
     排他制御による負荷を下げる目的（セマフォは namespace 毎に独立）。
 
 - 外部提供用に timer_maintenance(),timer_initialize(), prn_timer_headers() を
   新規作成（それぞれ、GAE_timer下のcheck_and_restore()、clear_all_timers()、
   prn_timer_header()をnamespaceをまとめてコールするためのラッパ関数)。


2010.05.07: version 0.0.1c
 - URLに全角が混ざっているとfetch_rpc()で例外が発生してしまう不具合修正。
   (fetch_rpc(),set_timer())
 
 - cron風の定刻指定時に、カンマ(,)区切とハイフン(-)区切を併用出来るように修正。
   (cron_getrange())（例："2-5,18,21-23"）
 
 - 異常系でタイマを再設定する場合、タイマ値を変更しないように修正(set_timer(),
   _reset_timer()にkeep_tvalueオプション追加)。
 

2010.01.18: version 0.0.1b
 - タイムアウトリスト取得処理(get_timeout_list())内で、リカバリしたタイマが消える
   不具合修正。
 
 - 修復処理（check_and_restore()）で、タイママップ(KEY_TIMER_MAP)がなかった場合に
   作成する処理を追加(memcache消去防止)。
 

2010.01.17: version 0.0.1a
 - 修復処理（check_and_restore()）で、リセットタイマ用メモリ領域(KEY_RESET_TIMERS)を
   クリアしてしまう不具合修正。
 
 - 修復処理（check_and_restore()）で、処理中にセマフォを解放するタイミングがあり、
   他の処理に割込まれる可能性が有ったのを修正。
 
 - timercycleの負荷分散に対応。
   ※予めキー(timerid)が決まっている場合にのみ負荷分散可能。
     GAE_Timer1st().get_timer_namespace_by_string()で返されたnamespaceを、
     GAE_Timer1st(namespace=namespace)として指定する。
   ※負荷分散上限はMAX_TIMER_TASK_NUMBER。
   ※cron.yamlへはnsid(timercycleオプション)=1～MAX_TIMER_TASK_NUMBERのものを登録。


2010.01.15: version 0.0.1
 - ソースを Web 上に公開。


2010.01.08: version -.-.-
 - 試作サービスとして公開。
   http://d.hatena.ne.jp/furyu-tei/20100108/gaecron


#------------------------------------------------------------------------------
"""
#■ end of file
