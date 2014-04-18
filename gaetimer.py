# -*- coding: utf-8 -*-

"""
gaetimer.py: Timer Library and Process for Google App Engine

License: The MIT license
Copyright (c) 2010 furyu-tei
"""

__author__ = 'furyutei@gmail.com'
__version__ = '0.0.1f'

import logging,re
import time,datetime
import urllib
import wsgiref.handlers
import hashlib

from google.appengine.ext import webapp
from google.appengine.api import urlfetch
from google.appengine.api import memcache
from google.appengine.api.labs import taskqueue
from google.appengine.api.urlfetch import InvalidURLError,DownloadError,ResponseTooLargeError

utcnow = datetime.datetime.utcnow
timedelta = datetime.timedelta
md5 = hashlib.md5

#{ // user parameters

PATH_BASE = u'/gaetimer%s'

# [2010/10/19] RPC_WAIT=False => True (GAEの仕様変更なのか、rpc.wait()しないとcallbackがされなくなったため)
#RPC_WAIT=False              # True: wait complete of RPC-fetch call
RPC_WAIT=True               # True: wait complete of RPC-fetch call
SAVE_CALLBACK_RESULT = True # True: save results of RPC-fetch call to memory-cache

DEBUG_FLAG = False          # for webapp.WSGIApplication()
DEBUG_LEVEL = logging.DEBUG # for logger
DEBUG = True                # False: disable log() (wrapper of logging.debug())

MAX_TIMEOUT_NUM = 20        # max number of asynchronous requests on timercycle()
MAX_CALL_NUM = 10           # max number of timercycle() called on one cycle (1 by cron.yaml, and max (MAX_CALL_NUM-1) by taskqueue())
MAX_TIMER_TASK_NUMBER = 10  # max number of timercycle() called by cron(1 by cron.yaml, and max (MAX_TIMER_TASK_NUMBER-1) by taskqueue())

MAX_RETRY_SEM_LOCK = 3      # max retry number of semaphore lock
INTV_RETRY_SEM_LOCK = 1     # wait for semaphore lock retry (sec)

DEFAULT_TZ_HOURS = +9       # timezone(hours) (UTC+DEFAULT_TZ_HOURS, JST=+9)
DEFAULT_DATETIME_FORMAT = '%Y/%m/%d %H:%M(JST)'

#} // end of user parameters


#{ // global variables

PATH_CYCLE = PATH_BASE % (u'/timercycle')
PATH_SHOWLIST = PATH_BASE % (u'/list')
PATH_SHOWLIST2 = PATH_BASE % (u'/list2')
PATH_SHOWCOUNTER = PATH_BASE % (u'/counter')
PATH_RESTORE = PATH_BASE % (u'/restore')
PATH_CLEARALL = PATH_BASE % (u'/clearall')
PATH_DEFAULT_TIMEOUT = PATH_BASE % (u'/timeout') # for test

TIMER_NAMESPACE_BASE = 'gae_timer'
TIMER_NAMESPACE_DEFAULT = TIMER_NAMESPACE_BASE

TIMER_NAMESPACE_2ND_BASE = 'gae_timer_2nd'
TIMER_NAMESPACE_2ND_DEFAULT = TIMER_NAMESPACE_2ND_BASE

TIMER_NAMESPACE_NEWEST_BASE = TIMER_NAMESPACE_2ND_BASE
TIMER_NAMESPACE_NEWEST_DEFAULT = TIMER_NAMESPACE_2ND_DEFAULT

KEY_SEM = 'key_semaphore'
KEY_THD = 'key_timer_header'
KEY_TID = 'key_timer_id'
KEY_TIMER_MAP = 'key_timer_map'
KEY_RESET_TIMERS = 'key_reset_timers'
KEY_STATUS_BASE = 'key_status_'

KEY_SEM_2ND = 'key_semaphore_2nd'
KEY_TIMER_MAP_2ND = 'key_timer_map_2nd'
KEY_TID_2ND = 'key_timer_id_2nd'
KEY_RESET_TIMERS_2ND = 'key_reset_timers_2nd'
KEY_STATUS_2ND_BASE = 'key_status_2nd_'

KEY_MAINTENANCE_MODE = 'key_maintenance_mode'

CONTENT_TYPE_PLAIN  ='text/plain; charset=utf-8'

#} // end of global variables


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
    payload = u'&'.join(pairs)
  
  if payload:
    if method=='POST':
      headers['Content-Type'] = 'application/x-www-form-urlencoded'
    else:
      url = u'%s?%s' % (url,payload)
      payload = None
  
  try:
    url = str(url)
  except:
    logerr(u'URL error: %s' % (url))
    if callback:
      callback(keyid,u'URL error')
    return None
  
  rpc = urlfetch.create_rpc(deadline=10)
  if callback:
    rpc.callback = lambda:handle_result(rpc)
  
  urlfetch.make_fetch_call(rpc=rpc, url=url, method=method, headers=headers, payload=payload)
  
  return rpc
#} // end of def fetch_rpc()


#{ // def get_namespace_version()
re_ns_first = re.compile(u'^%s\d*$' % (TIMER_NAMESPACE_BASE))
re_ns_second = re.compile(u'^%s\d*$' % (TIMER_NAMESPACE_2ND_BASE))
def get_namespace_version(namespace):
  ver = '0'
  while True:
    if not isinstance(namespace,basestring):
      break
    if re_ns_second.search(namespace):
      ver = '2'
      break
    if re_ns_first.search(namespace):
      ver = '1'
      break
    break
  return ver
#} // end of def get_namespace_version()


#{ // def cron_getrange()
re_asta_sla = re.compile(u'^\*/(\d+)$')
re_hyphen = re.compile(u'^(\d+)-(\d+)')
def cron_getrange(field,min,max):
  if field=='*':
    return range(min,1+max)
  mrslt = re_asta_sla.search(field)
  if mrslt:
    _step = int(mrslt.group(1))
    if 0<_step:
      return range(min,1+max,_step)
    else:
      return []
  
  def _getrange(elm):
    mrslt = re_hyphen.search(elm)
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
re_chop_space = re.compile(u'^\s+|\s+$')
re_space = re.compile(u'\s+')
def cron_nexttime(crontime,tz_hours=DEFAULT_TZ_HOURS,lasttime=None):
  if not isinstance(crontime,basestring): return None
  
  fs = re_space.split(re_chop_space.sub(r'',crontime))
  if len(fs)!=5: return None
  
  rmin = cron_getrange(fs[0],0,59)
  if len(rmin)<=0: return None
  
  rhour = cron_getrange(fs[1],0,23)
  if len(rhour)<=0: return None
  
  rday = cron_getrange(fs[2],1,31)
  if len(rday)<=0: return None
  
  rmonth = cron_getrange(fs[3],1,12)
  if len(rmonth)<=0: return None
  
  rwday = cron_getrange(fs[4],0,7)
  if len(rwday)<=0: return None
  # 0(Sunday) => 7(Sunday) for isoweekday()
  if rwday[0] == 0:
    rwday.pop(0)
    if len(rwday)==0 or rwday[-1] != 7:
      rwday.append(7)
  
  if not lasttime:
    lasttime = utcnow()
  
  dt = lasttime + timedelta(hours=tz_hours)
  
  tmin = dt.minute
  dmin = None
  for _min in rmin:
    if tmin < _min:
      dmin = _min - tmin
      break
  if dmin == None:
    dmin = 60 + rmin[0] - tmin
  
  dt = dt + timedelta(minutes=dmin)
  
  thour = dt.hour
  dhour = None
  for _hour in rhour:
    if thour <= _hour:
      dhour = _hour - thour
      break
  if dhour == None:
    dhour = 24 + rhour[0] - thour
  
  dt = dt + timedelta(hours=dhour)
  
  day_or_wday = False
  if fs[2]!='*' and fs[4]!='*':
    day_or_wday = True
  for ci in range(366):
    (tmonth,tday,twday) = (dt.month,dt.day,dt.isoweekday())
    if tmonth in rmonth:
      if day_or_wday and ((tday in rday) or (twday in rwday)):
        break
      elif (tday in rday) and (twday in rwday):
        break
    dt = dt + timedelta(days=1)
  
  if 365<=ci:
    return None
  
  dt = dt - timedelta(hours=tz_hours,seconds=dt.second,microseconds=dt.microsecond)
  
  return dt
#} // end of def cron_nexttime()


#{ // class SemaphoreError()
class SemaphoreError(Exception):
  def __init__(self,value):
    self.value = value
  
  def __str__(self):
    return self.value
#} // end of class SemaphoreError()


#{ // class DuplicateTimerError()
class DuplicateTimerError(Exception):
  def __init__(self,value):
    self.value = value
  
  def __str__(self):
    return self.value
#} // end of class DuplicateTimerError()


#{ // class GAE_Timer1st()
class TIMER_HEADER(object):
  def __init__(self):
    self.first = None
    self.last = None
    self.count = 0
    self.count_set = 0
    self.count_reset = 0
    self.count_release = 0
    self.count_timeout = 0

class TIMER_INFO(object):
  def __init__(self):
    self.timerid = None
    self.prev = None
    self.next = None
    self.minutes = None
    self.crontime = None
    self.tz_hours = None
    self.timeout = None
    self.url = None
    self.user_id = None
    self.user_info = None
    self.repeat = False

class GAE_Timer1st(object):
  def __init__(self,init=None,namespace=TIMER_NAMESPACE_DEFAULT,def_timeout_path=PATH_DEFAULT_TIMEOUT,ignore_duplicate=True):
    if not namespace:
      namespace = TIMER_NAMESPACE_DEFAULT
    self.namespace = namespace
    self.def_timeout_path = def_timeout_path
    self.ignore_duplicate = ignore_duplicate
    self._timer_init()
    self.curtime = utcnow()
  
  def get_timer_namespace_by_string(self,base_str):
    return TIMER_NAMESPACE_BASE+ str(1+(int(md5(base_str).hexdigest(),16)%MAX_TIMER_TASK_NUMBER))
  
  def get_timer_namespace_by_number(self,base_num):
    return self.get_timer_namespace_by_string(str(base_num))
  
  def _sem_init(self):
    memcache.delete(key=KEY_SEM,namespace=self.namespace)
    loginfo('init semaphore (namespace=%s)' % (self.namespace))
  
  def _sem_lock(self):
    try:
      _num = memcache.incr(key=KEY_SEM,initial_value=0,namespace=self.namespace)
      if _num == 1:
        log('_sem_lock: success (namespace=%s)' % (self.namespace))
        return True
      else:
        memcache.decr(key=KEY_SEM,namespace=self.namespace)
        log('_sem_lock: failure (number=%s) (namespace=%s)' % (str(_num),self.namespace))
        return False
    except Exception, s:
      logerr('_sem_lock: %s (namespace=%s)' % (str(s),self.namespace))
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
      _num = memcache.decr(key=KEY_SEM,namespace=self.namespace)
      if _num == 0:
        log('_sem_unlock: success (namespace=%s)' % (self.namespace))
      else:
        log('_sem_unlock: success (namespace=%s) remain number=%s (temporary conflict with others)' % (self.namespace,str(_num)))
    except Exception, s:
      logerr('_sem_unlock: %s (namespace=%s)' % (str(s),self.namespace))
  
  def _timer_init(self):
    try:
      header = memcache.get(key=KEY_THD,namespace=self.namespace)
    except:
      header = None
    if not header:
      try:
        self.clear_all_timers()
      except:
        pass
  
  def _get_timerid(self):
    return str(memcache.incr(key=KEY_TID,initial_value=0,namespace=self.namespace))
  
  def get_timer_namespace(self):
    return self.namespace
  
  def get_def_timeout_path(self):
    return self.def_timeout_path
  
  def clear_all_timers(self):
    loginfo(u'clear_all_timers: start (namespace=%s)' % (self.namespace))
    namespace = self.namespace
    self._sem_init()
    self._sem_lock_retry()
    header = TIMER_HEADER()
    memcache.set(key=KEY_THD,value=header,time=0,namespace=namespace)
    memcache.set(key=KEY_TID,value=0,time=0,namespace=namespace)
    memcache.set(key=KEY_TIMER_MAP,value={},time=0,namespace=namespace)
    memcache.set(key=KEY_RESET_TIMERS,value=[],time=0,namespace=namespace)
    self._sem_unlock()
    loginfo(u'clear_all_timers: end')
  
  def set_timer(self,minutes=None,crontime=None,tz_hours=DEFAULT_TZ_HOURS,url=None,user_id=None,user_info=None,repeat=True,timerid=None,sem=True,prn=False,tvalue=None):
    log(u'set_timer (namespace=%s)' % (self.namespace))
    
    try:
      url = str(url)
    except:
      logerr(u'URL error: %s' % (url))
      return None
    
    timer = TIMER_INFO()
    timer.minutes = minutes
    timer.crontime = crontime
    timer.tz_hours = tz_hours
    timer.url = url
    timer.user_id = user_id
    timer.user_info = user_info
    timer.repeat = repeat
    
    if tvalue:
      timeout = tvalue
    elif crontime:
      timeout = cron_nexttime(crontime,tz_hours=tz_hours)
      if not timeout:
        return None
    else:
      if not isinstance(minutes,(int,long)):
        return None
      #timeout = utcnow() + timedelta(minutes=minutes)
      timeout = self.curtime + timedelta(minutes=minutes)
    
    timer.timeout = timeout
    
    namespace = self.namespace
    
    if sem:
      self._sem_lock_retry()
    
    if timerid:
      timerid = str(timerid)
      flg_reset = True
    else:
      flg_reset = False
      timerid = self._get_timerid()
    
    timer.timerid = timerid
    
    header = memcache.get(key=KEY_THD,namespace=namespace)
    timer_map = memcache.get(key=KEY_TIMER_MAP,namespace=namespace)
    
    if timer_map.get(timerid):
      if sem:
        self._sem_unlock()
      err_str = u'set_timer: duplicate timerid=%s to set' % (timerid)
      if self.ignore_duplicate:
        loginfo(err_str)
      else:
        logerr(err_str)
        raise DuplicateTimerError(err_str)
      return timerid
    
    tmp_tid = header.first
    if not tmp_tid:
      header.first = header.last = timerid
    else:
      (prv_tid,prv_timer) = (None,None)
      while True:
        tmp_timer = timer_map.get(tmp_tid)
        
        if timeout<tmp_timer.timeout:
          timer.prev = prv_tid
          timer.next = tmp_tid
          if prv_timer:
            prv_timer.next = timerid
          else:
            header.first = timerid
          tmp_timer.prev = timerid
          break
        
        if not tmp_timer.next:
          timer.prev = tmp_tid
          timer.next = None
          tmp_timer.next = header.last = timerid
          timer_map[tmp_tid] = tmp_timer
          break
        
        prv_tid = tmp_tid
        prv_timer = tmp_timer
        
        tmp_tid = tmp_timer.next
    
    timer_map[timerid] = timer
    
    if flg_reset:
      header.count_reset +=1
    else:
      header.count_set +=1
    header.count +=1
    
    memcache.set(key=KEY_TIMER_MAP,value=timer_map,time=0,namespace=namespace)
    memcache.set(key=KEY_THD,value=header,time=0,namespace=namespace)
    
    if sem:
      self._sem_unlock()
    
    if flg_reset:
      log(u'reset timer(%s): next timeout=%s' % (timerid,timer.timeout))
    else:
      try:
        self.save_last_status(timerid=timerid,last_timeout=u'',last_result=u'')
      except:
        pass
      log(u'set timer(%s): next timeout=%s' % (timerid,timer.timeout))
    
    if prn:
      self.prn_timer(timer=timer)
    
    return timerid
  
  def rel_timer(self,timerid,sem=True,prn=False):
    timerid=str(timerid)
    log(u'rel_timer: timerid=%s (namespace=%s)' % (timerid,self.namespace))
    
    namespace = self.namespace
    
    if sem:
      self._sem_lock_retry()
    
    timer_map = memcache.get(key=KEY_TIMER_MAP,namespace=namespace)
    
    timer = timer_map.get(timerid)
    
    if timer:
      if prn:
        self.prn_timer(timer=timer)
      
      header = memcache.get(key=KEY_THD,namespace=namespace)
      prv_tid = timer.prev
      nxt_tid = timer.next
      
      if prv_tid:
        prv_timer = timer_map.get(prv_tid)
        prv_timer.next = nxt_tid
      else:
        header.first = nxt_tid
      
      if nxt_tid:
        nxt_timer = timer_map.get(nxt_tid)
        nxt_timer.prev = prv_tid
      else:
        header.last = prv_tid
      
      del(timer_map[timerid])
      
      header.count_release +=1
      header.count -=1
      
      memcache.set(key=KEY_TIMER_MAP,value=timer_map,time=0,namespace=namespace)
      memcache.set(key=KEY_THD,value=header,time=0,namespace=namespace)
    
    if sem:
      self._sem_unlock()
    
    if timer:
      log(u'release timer(%s) complete' % (timerid))
    else:
      log(u'timerid=%s to release not found' % (timerid))
    
  def _reset_timer(self,timer,use_same_id=True,sem=True,prn=False,keep_tvalue=False):
    if use_same_id:
      timer_id = timer.timerid
    else:
      timer_id = None
    
    if keep_tvalue:
      tvalue = timer.timeout
    else:
      tvalue = None
    
    self.set_timer(
      minutes = timer.minutes,
      crontime = timer.crontime,
      tz_hours = timer.tz_hours,
      url = timer.url,
      user_id = timer.user_id,
      user_info = timer.user_info,
      repeat = timer.repeat,
      timerid = timer_id,
      sem = sem,
      prn = prn,
      tvalue = tvalue,
    )
  
  def get_timeout_list(self,max_num=0):
    log('check timeout timers: start (namespace=%s)' % (self.namespace))
    
    #curtime = utcnow()
    curtime = self.curtime
    flg_remain = False
    namespace = self.namespace
    _reset_timer = self._reset_timer
    
    try:
      self._sem_lock_retry()
    except:
      self.check_and_restore()
      try:
        self._sem_lock_retry()
      except:
        return ([],True)
    
    reset_list = memcache.get(key=KEY_RESET_TIMERS,namespace=namespace)
    if reset_list:
      logerr(u'recover reset list')
      for timer in reset_list:
        _reset_timer(timer,sem=False,keep_tvalue=True)
      memcache.set(key=KEY_RESET_TIMERS,value=[],time=0,namespace=namespace)
    
    timer_map = memcache.get(key=KEY_TIMER_MAP,namespace=namespace)
    header = memcache.get(key=KEY_THD,namespace=namespace)
    self.prn_timer_header(header)
    
    timeout_list = []
    reset_list = []
    
    tmp_tid = header.first
    last_timer = None
    count = 0
    while tmp_tid:
      if 0<max_num and max_num<=count:
        flg_remain = True
        break
      tmp_timer = timer_map.get(tmp_tid)
      if curtime < tmp_timer.timeout:
        break
      tmp_timer = timer_map.pop(tmp_tid)
      timeout_list.append(tmp_timer)
      if tmp_timer.repeat:
        reset_list.append(tmp_timer)
      last_timer = tmp_timer
      count +=1
      tmp_tid = tmp_timer.next
    
    reset_list.reverse()
    memcache.set(key=KEY_RESET_TIMERS,value=reset_list,time=0,namespace=namespace)
    
    tnum = len(timeout_list)
    if 0<tnum:
      header.count_timeout +=tnum
      header.count -=tnum
      nxt_tid = last_timer.next
      header.first = nxt_tid
      if nxt_tid:
        nxt_timer = timer_map.get(nxt_tid)
        nxt_timer.prev = None
      if not header.first:
        header.last = None
      
      #memcache.set(key=KEY_TIMER_MAP,value=timer_map,time=0,namespace=namespace)
      #memcache.set(key=KEY_THD,value=header,time=0,namespace=namespace)
    
    # // 更新なしの場合でもmemcacheのリフレッシュのために必ず保存しなおす
    memcache.set(key=KEY_TIMER_MAP,value=timer_map,time=0,namespace=namespace)
    memcache.set(key=KEY_THD,value=header,time=0,namespace=namespace)
    
    for timer in reset_list:
      _reset_timer(timer,sem=False)
    memcache.set(key=KEY_RESET_TIMERS,value=[],time=0,namespace=namespace)
    
    log('check timeout timers: end (namespace=%s)' % (self.namespace))
    self.prn_timer_header()
    
    self._sem_unlock()
    
    return (timeout_list,flg_remain)
  
  def check_and_restore(self):
    loginfo('check timer queue (namespace=%s)' % (self.namespace))
    namespace = self.namespace
    
    if not self._sem_lock():
      self._sem_init()
      self._sem_lock_retry()
    
    header = memcache.get(key=KEY_THD,namespace=namespace)
    timer_map = memcache.get(key=KEY_TIMER_MAP,namespace=namespace)
    if not timer_map:
      timer_map = {}
      memcache.set(key=KEY_TIMER_MAP,value=timer_map,time=0,namespace=namespace)
    
    try:
      (header,cnt,rcnt) = self.get_tim_counter(header=header,timer_map=timer_map,sem=False)
      if header.count == cnt and cnt == rcnt:
        self._sem_unlock()
        log(u'timer queue: OK')
        log(u'len(timer_map)=%d' % (len(timer_map)))
        self.prn_timer_header(header)
        return
    except:
      pass
    
    logerr(u'timer queue broken (namespace=%s)' % (self.namespace))
    loginfo('restore timer queue: <before> (%s)' % (self.namespace))
    loginfo(u'len(timer_map)=%d' % (len(timer_map)))
    if header:
      self.prn_timer_header(header)
    else:
      loginfo(u'header broken')
    
    #self._sem_unlock()
    
    #self.clear_all_timers() # !!! NG: clear backup of reset timers, and another task can access timer areas !!!
    
    reset_list = memcache.get(key=KEY_RESET_TIMERS,namespace=namespace)
    if not reset_list:
      reset_list = []
    
    memcache.set(key=KEY_TIMER_MAP,value={},time=0,namespace=namespace)
    memcache.set(key=KEY_RESET_TIMERS,value=[],time=0,namespace=namespace)
    
    _reset_timer = self._reset_timer
    
    for ci in range(3):
      header = TIMER_HEADER()
      memcache.set(key=KEY_THD,value=header,time=0,namespace=namespace)
      
      #self._sem_lock_retry()
      
      try:
        max_id = 0
        for (timerid,timer) in timer_map.items():
          try:
            _tid = int(timerid)
            if max_id<_tid:
              max_id = _tid
          except:
            pass
          _reset_timer(timer,sem=False,keep_tvalue=True) # occasionally raise exception (confilict with timercycle())
        
        for timer in reset_list:
          try:
            _tid = int(timer.timerid)
            if max_id<_tid:
              max_id = _tid
          except:
            pass
          _reset_timer(timer,sem=False,keep_tvalue=True) # occasionally raise exception (confilict with timercycle())
        break
      except:
        continue
    
    memcache.set(key=KEY_TID,value=max_id,time=0,namespace=namespace)
    
    self._sem_unlock()
    
    loginfo('restore timer queue: <after> (namespace=%s)' % (self.namespace))
    self.prn_timer_header()
  
  def prn_timer_header(self,header=None):
    if not header:
      header = memcache.get(key=KEY_THD,namespace=self.namespace)
    hmems=['first','last','count','count_set','count_reset','count_release','count_timeout']
    log(u'[header] (namespace=%s)' % (self.namespace))
    for mem in hmems:
      log(u' %s = %s' % (mem,getattr(header,mem,u'')))
    log('')
  
  def prn_timer(self,timer_map=None,timerid=None,timer=None):
    if timer:
      timerid = timer.timerid
    else:
      if not timerid:
        return
      if not timer_map:
        timer_map = memcache.get(key=KEY_TIMER_MAP,namespace=self.namespace)
        if not timer_map: # critical error
          logerr(u'prn_timer(): timer_map not found.')
          return
      timerid = str(timerid)
      timer = timer_map.get(timerid)
    
    tmems=['timerid','prev','next','minutes','crontime','tz_hours','timeout','url','user_id','user_info','repeat']
    log(u' [timer(id=%s)] (namespace=%s)' % (timerid,self.namespace))
    for mem in tmems:
      log(u'  %s = %s' % (mem,getattr(timer,mem,u'')))
    log('')
  
  def prn_timer_short(self,timer_map=None,timerid=None,timer=None):
    if timer:
      timerid = timer.timerid
    else:
      if not timerid:
        return
      if not timer_map:
        timer_map = memcache.get(key=KEY_TIMER_MAP,namespace=self.namespace)
        if not timer_map: # critical error
          logerr(u'prn_timer_short(): timer_map not found.',self.namespace)
          return
      timerid = str(timerid)
      timer = timer_map.get(timerid)
    
    tmems=['url','user_id','user_info']
    log(u' [timer(id=%s)] (namespace=%s)' % (timerid,self.namespace))
    for mem in tmems:
      log(u'  %s = %s' % (mem,getattr(timer,mem,u'')))
    log('')
  
  def prn_tim_list(self,header=None,timer_map=None,sem=True):
    log(u'prn_tim_list: start (namespace=%s)' % (self.namespace))
    prn_timer = self.prn_timer
    if sem:
      self._sem_lock_retry()
    if not header:
      header = memcache.get(key=KEY_THD,namespace=self.namespace)
    self.prn_timer_header(header)
    if not timer_map:
      timer_map = memcache.get(key=KEY_TIMER_MAP,namespace=self.namespace)
    tmp_tid = header.first
    while tmp_tid:
      tmp_timer = timer_map.get(tmp_tid)
      prn_timer(timer_map=timer_map,timer=tmp_timer)
      tmp_tid = tmp_timer.next
    if sem:
      self._sem_unlock()
    log(u'prn_tim_list: end (namespace=%s)' % (self.namespace))

  def prn_tim_list2(self,header=None,timer_map=None,sem=True):
    log(u'prn_tim_list2: start (namespace=%s)' % (self.namespace))
    if sem:
      try:
        self._sem_lock_retry()
      except:
        self._sem_init()
        self._sem_lock_retry()
    
    self.prn_timer_header()
    prn_timer = self.prn_timer
    
    if not timer_map:
      timer_map = memcache.get(key=KEY_TIMER_MAP,namespace=self.namespace)
      if not timer_map:
        timer_map = {}
    
    for (timerid,timer) in timer_map.items():
      log(u'<timerid=%s>' % (timerid))
      prn_timer(timer_map=timer_map,timer=timer)
    
    if sem:
      self._sem_unlock()
    
    log(u'prn_tim_list2: end (namespace=%s)' % (self.namespace))
  
  def get_tim_counter(self,header=None,timer_map=None,sem=True):
    log('get timer counter (namespace=%s)' % (self.namespace))
    if sem:
      self._sem_lock_retry()
      
    if not header:
      header = memcache.get(key=KEY_THD,namespace=self.namespace)
    if not timer_map:
      timer_map = memcache.get(key=KEY_TIMER_MAP,namespace=self.namespace)
    
    tmp_tid = header.first
    cnt = 0
    while tmp_tid:
      tmp_timer = timer_map.get(tmp_tid)
      tmp_tid = tmp_timer.next
      cnt += 1
    
    tmp_tid = header.last
    rcnt = 0
    while tmp_tid:
      tmp_timer = timer_map.get(tmp_tid)
      tmp_tid = tmp_timer.prev
      rcnt += 1
    
    if sem:
      self._sem_unlock()
    
    return (header,cnt,rcnt)
  
  def prn_tim_counter(self):
    (header,cnt,rcnt) = self.get_tim_counter()
    
    self.prn_timer_header(header)
    log(u'count=%d (reverse=%d)' % (cnt,rcnt))

  def save_last_status(self,timerid,last_timeout=u'',last_result=u''):
    memcache.set(key=KEY_STATUS_BASE+str(timerid),value=dict(last_timeout=last_timeout,last_result=last_result),time=0,namespace=self.namespace)
  
  def get_last_status(self,timerid):
    last_status = memcache.get(key=KEY_STATUS_BASE+str(timerid),namespace=self.namespace)
    if not last_status:
      last_status = dict(last_timeout=u'',last_result=u'')
    return last_status

  def get_next_time(self,timerid,fmt=DEFAULT_DATETIME_FORMAT):
    next_time = u''
    timer_map = memcache.get(key=KEY_TIMER_MAP,namespace=self.namespace)
    timer = timer_map.get(str(timerid))
    if timer:
      try:
        next_time = (timer.timeout+timedelta(hours=DEFAULT_TZ_HOURS)).strftime(fmt)
      except:
        next_time = u''
    return next_time
  
  def get_timer_map(self):
    timer_map = memcache.get(key=KEY_TIMER_MAP,namespace=self.namespace)
    if not timer_map:
      timer_map = {}
    return timer_map
  
#} // end of class GAE_Timer1st()


#{ // class GAE_Timer2nd()
class TIMER_HEADER_2ND(object):
  def __init__(self):
    self.first = None
    self.last = None
    self.count = 0
    self.count_set = 0
    self.count_reset = 0
    self.count_release = 0
    self.count_timeout = 0

class TIMER_INFO_2ND(object):
  def __init__(self):
    self.timerid = None
    self.prev = None
    self.next = None
    self.minutes = None
    self.crontime = None
    self.tz_hours = None
    self.timeout = None
    self.url = None
    self.user_id = None
    self.user_info = None
    self.repeat = False
    self.same_count = 0
    self.same_prev = None
    self.same_next = None

class TIMER_MAP_2ND(object):
  def __init__(self,header=None,timer_map=None):
    if not header:
      header = TIMER_HEADER_2ND()
    if not timer_map:
      timer_map = {}
    self.header = header
    self.timer_map = timer_map

class GAE_Timer2nd(object):
  def __init__(self,init=None,namespace=TIMER_NAMESPACE_2ND_DEFAULT,def_timeout_path=PATH_DEFAULT_TIMEOUT,ignore_duplicate=True):
    if not namespace:
      namespace = TIMER_NAMESPACE_2ND_DEFAULT
    self.namespace = namespace
    self.def_timeout_path = def_timeout_path
    self.ignore_duplicate = ignore_duplicate
    self._timer_init()
    self.curtime = utcnow()
  
  def get_timer_namespace_by_string(self,base_str):
    return TIMER_NAMESPACE_2ND_BASE+ str(1+(int(md5(base_str).hexdigest(),16)%MAX_TIMER_TASK_NUMBER))
  
  def get_timer_namespace_by_number(self,base_num):
    return self.get_timer_namespace_by_string(str(base_num))
  
  def _sem_init(self):
    memcache.delete(key=KEY_SEM_2ND,namespace=self.namespace)
    loginfo('init semaphore (namespace=%s)' % (self.namespace))
  
  def _sem_lock(self):
    try:
      _num = memcache.incr(key=KEY_SEM_2ND,initial_value=0,namespace=self.namespace)
      if _num == 1:
        log('_sem_lock: success (namespace=%s)' % (self.namespace))
        return True
      else:
        memcache.decr(key=KEY_SEM_2ND,namespace=self.namespace)
        log('_sem_lock: failure (number=%s) (namespace=%s)' % (str(_num),self.namespace))
        return False
    except Exception, s:
      logerr('_sem_lock: %s (namespace=%s)' % (str(s),self.namespace))
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
      _num = memcache.decr(key=KEY_SEM_2ND,namespace=self.namespace)
      if _num == 0:
        log('_sem_unlock: success (namespace=%s)' % (self.namespace))
      else:
        log('_sem_unlock: success (namespace=%s) remain number=%s (temporary conflict with others)' % (self.namespace,str(_num)))
    except Exception, s:
      logerr('_sem_unlock: %s (namespace=%s)' % (str(s),self.namespace))
  
  def _timer_init(self):
    try:
      timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=self.namespace)
    except:
      timer_map_2nd = None
    if not timer_map_2nd:
      try:
        self.clear_all_timers()
      except:
        pass
  
  def _get_timerid(self):
    return str(memcache.incr(key=KEY_TID_2ND,initial_value=0,namespace=self.namespace))
  
  def get_timer_namespace(self):
    return self.namespace
  
  def get_def_timeout_path(self):
    return self.def_timeout_path
  
  def clear_all_timers(self):
    loginfo(u'clear_all_timers: start (namespace=%s)' % (self.namespace))
    namespace = self.namespace
    self._sem_init()
    self._sem_lock_retry()
    timer_map_2nd = TIMER_MAP_2ND()
    memcache.set(key=KEY_TIMER_MAP_2ND,value=timer_map_2nd,time=0,namespace=namespace)
    memcache.set(key=KEY_TID_2ND,value=0,time=0,namespace=namespace)
    memcache.set(key=KEY_RESET_TIMERS_2ND,value=[],time=0,namespace=namespace)
    self._sem_unlock()
    loginfo(u'clear_all_timers: end')
  
  def set_timer(self,minutes=None,crontime=None,tz_hours=DEFAULT_TZ_HOURS,url=None,user_id=None,user_info=None,repeat=True,timerid=None,sem=True,prn=False,tvalue=None,old_timer=None,timer_map_2nd=None):
    log(u'set_timer (namespace=%s)' % (self.namespace))
    
    if old_timer:
      timer = old_timer
      timer.prev = None
      timer.next = None
      timer.same_count = 0
      timer.same_prev = None
      timer.same_next = None
      minutes = timer.minutes
      crontime = timer.crontime
      tz_hours = timer.tz_hours
    else:
      try:
        url = str(url)
      except:
        logerr(u'URL error: %s' % (url))
        return None
      timer = TIMER_INFO_2ND()
      timer.minutes = minutes
      timer.crontime = crontime
      timer.tz_hours = tz_hours
      timer.url = url
      timer.user_id = user_id
      timer.user_info = user_info
      timer.repeat = repeat
    
    if tvalue:
      timeout = tvalue
    elif crontime:
      timeout = cron_nexttime(crontime,tz_hours=tz_hours)
      if not timeout:
        return None
    else:
      if not isinstance(minutes,(int,long)):
        return None
      #timeout = utcnow() + timedelta(minutes=minutes)
      timeout = self.curtime + timedelta(minutes=minutes)
    
    timer.timeout = timeout
    
    namespace = self.namespace
    
    if sem:
      self._sem_lock_retry()
    
    if timerid:
      timerid = str(timerid)
      flg_reset = True
    else:
      flg_reset = False
      timerid = self._get_timerid()
    
    timer.timerid = timerid
    
    flg_save = False
    if not timer_map_2nd:
      flg_save = True
      timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=namespace)
    
    if not timer_map_2nd: # critical error
      logerr(u'set_timer(): timer_map_2nd not found.')
      if sem:
        self._sem_unlock()
        return None
    
    header = timer_map_2nd.header
    timer_map = timer_map_2nd.timer_map
    
    if timer_map.get(timerid):
      if sem:
        self._sem_unlock()
      err_str = u'set_timer: duplicate timerid=%s to set' % (timerid)
      if self.ignore_duplicate:
        loginfo(err_str)
      else:
        logerr(err_str)
        raise DuplicateTimerError(err_str)
      return timerid
    
    tmp_tid = header.first
    if not tmp_tid:
      header.first = header.last = timerid
    else:
      (prv_tid,prv_timer) = (None,None)
      while True:
        tmp_timer = timer_map.get(tmp_tid)
        
        if timeout<tmp_timer.timeout:
          _td = -(tmp_timer.timeout-timeout).seconds//60
        else:
          _td = (timeout-tmp_timer.timeout).seconds//60
        
        if _td == 0:
          # // 同時タイムアウト
          if tmp_timer.same_next:
            tmp_same_timer = timer_map.get(tmp_timer.same_next)
            tmp_timer.same_next = timerid
            timer.same_prev = tmp_timer.timerid
            timer.same_next = tmp_same_timer.timerid
            tmp_same_timer.same_prev = timerid
          else:
            tmp_timer.same_next = timerid
            timer.same_prev = tmp_timer.timerid
          tmp_timer.same_count+=1
          break
        
        if _td < 0:
          # // より早くタイムアウト
          timer.prev = prv_tid
          timer.next = tmp_tid
          if prv_timer:
            prv_timer.next = timerid
          else:
            header.first = timerid
          tmp_timer.prev = timerid
          break
        
        # // より遅くタイムアウト
        if not tmp_timer.next:
          # // 一番後ろ
          timer.prev = tmp_tid
          timer.next = None
          tmp_timer.next = header.last = timerid
          timer_map[tmp_tid] = tmp_timer
          break
        
        prv_tid = tmp_tid
        prv_timer = tmp_timer
        
        tmp_tid = tmp_timer.next
    
    timer_map[timerid] = timer
    
    if flg_reset:
      header.count_reset +=1
    else:
      header.count_set +=1
    header.count +=1
    
    if flg_save:
      #memcache.set(key=KEY_TIMER_MAP_2ND,value=timer_map_2nd,time=0,namespace=namespace)
      memcache.set(key=KEY_TIMER_MAP_2ND,value=timer_map_2nd,time=3600,namespace=namespace)
    
    if sem:
      self._sem_unlock()
    
    if flg_reset:
      log(u'reset timer(%s): next timeout=%s' % (timerid,timer.timeout))
    else:
      try:
        self.save_last_status(timerid=timerid,last_timeout=u'',last_result=u'')
      except:
        pass
      log(u'set timer(%s): next timeout=%s' % (timerid,timer.timeout))
    
    if prn:
      self.prn_timer(timer=timer)
    
    return timerid
  
  def rel_timer(self,timerid,sem=True,prn=False,timer_map_2nd=None):
    timerid=str(timerid)
    log(u'rel_timer: timerid=%s (namespace=%s)' % (timerid,self.namespace))
    
    namespace = self.namespace
    
    if sem:
      self._sem_lock_retry()
    
    if not timer_map_2nd:
      timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=namespace)
    
    if not timer_map_2nd: # critical error
      logerr(u'rel_timer(): timer_map_2nd not found.')
      if sem:
        self._sem_unlock()
        return None
    
    header = timer_map_2nd.header
    timer_map = timer_map_2nd.timer_map
    
    timer = timer_map.get(timerid)
    
    if timer:
      if prn:
        self.prn_timer(timer=timer)
      
      while True:
        # // 同時タイマチェック
        if 0<timer.same_count:
        
          # // 同時タイマ有りかつtimerが先頭(same_countが入っているのは先頭のみ)
          tmp_same_timer = timer_map.get(timer.same_next)
          tmp_same_timer.same_prev = None
          tmp_same_timer.same_count = timer.same_count-1
          
          tmp_same_timerid = tmp_same_timer.timerid
          prv_tid = tmp_same_timer.prev = timer.prev
          nxt_tid = tmp_same_timer.next = timer.next
          
          if prv_tid:
            prv_timer = timer_map.get(prv_tid)
            prv_timer.next = tmp_same_timerid
          else:
            header.first = tmp_same_timerid
          
          if nxt_tid:
            nxt_timer = timer_map.get(nxt_tid)
            nxt_timer.prev = tmp_same_timerid
          else:
            header.last = tmp_same_timerid
          break
        else:
          # // 同時タイマがない、もしくはtimerが先頭以外
          if timer.same_prev:
            # // 同時タイマあり(先頭以外は必ずsame_prev有り)
            if timer.same_next:
              tmp_same_timer = timer_map.get(timer.same_next)
              tmp_same_timer.same_prev = timer.same_prev
            tmp_same_timer = timer_map.get(timer.same_prev)
            tmp_same_timer.same_next = timer.same_next
            # // 先頭に遡って、カウントダウン
            while tmp_same_timer.same_prev:
              tmp_same_timer = timer_map.get(tmp_same_timer.same_prev)
            tmp_same_timer.same_count -= 1
            break
        
        prv_tid = timer.prev
        nxt_tid = timer.next
        
        if prv_tid:
          prv_timer = timer_map.get(prv_tid)
          prv_timer.next = nxt_tid
        else:
          header.first = nxt_tid
        
        if nxt_tid:
          nxt_timer = timer_map.get(nxt_tid)
          nxt_timer.prev = prv_tid
        else:
          header.last = prv_tid
        
        break
      
      del(timer_map[timerid])
      
      header.count_release +=1
      header.count -=1
      
      #memcache.set(key=KEY_TIMER_MAP_2ND,value=timer_map_2nd,time=0,namespace=namespace)
      memcache.set(key=KEY_TIMER_MAP_2ND,value=timer_map_2nd,time=3600,namespace=namespace)
    
    if sem:
      self._sem_unlock()
    
    if timer:
      log(u'release timer(%s) complete' % (timerid))
    else:
      log(u'timerid=%s to release not found' % (timerid))
    
  def _reset_timer(self,timer,use_same_id=True,sem=True,prn=False,keep_tvalue=False,timer_map_2nd=None):
    if use_same_id:
      timer_id = timer.timerid
    else:
      timer_id = None
    
    if keep_tvalue:
      tvalue = timer.timeout
    else:
      tvalue = None
    
    self.set_timer(
      timerid = timer_id,
      sem = sem,
      prn = prn,
      tvalue = tvalue,
      old_timer = timer,
      timer_map_2nd = timer_map_2nd,
    )
  
  def get_timeout_list(self,max_num=0):
    log('check timeout timers: start (namespace=%s)' % (self.namespace))
    
    #curtime = utcnow()
    curtime = self.curtime
    flg_remain = False
    namespace = self.namespace
    _reset_timer = self._reset_timer
    
    try:
      self._sem_lock_retry()
    except:
      self.check_and_restore()
      try:
        self._sem_lock_retry()
      except:
        return ([],True)
    
    timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=namespace)
    
    if not timer_map_2nd: # critical error
      logerr(u'get_timeout_list(): timer_map_2nd not found.')
      self._sem_unlock()
      return ([],False)
    
    reset_list = memcache.get(key=KEY_RESET_TIMERS_2ND,namespace=namespace)
    if reset_list:
      logerr(u'recover reset list')
      for timer in reset_list:
        _reset_timer(timer,sem=False,keep_tvalue=True)
      memcache.set(key=KEY_RESET_TIMERS_2ND,value=[],time=0,namespace=namespace)
    
    header = timer_map_2nd.header
    timer_map = timer_map_2nd.timer_map
    
    self.prn_timer_header(header)
    
    timeout_list = []
    reset_list = []
    
    tmp_tid = header.first
    last_timer = None
    count = 0
    while tmp_tid:
      if 0<max_num and max_num<=count:
        flg_remain = True
        break
      tmp_timer = timer_map.get(tmp_tid)
      if curtime < tmp_timer.timeout:
        break
      tmp_timer = timer_map.pop(tmp_tid)
      timeout_list.append(tmp_timer)
      if tmp_timer.repeat:
        reset_list.append(tmp_timer)
      
      # // 同時タイマチェック
      next_timerid = tmp_timer.same_next
      while next_timerid:
        tmp_same_timer = timer_map.pop(next_timerid)
        timeout_list.append(tmp_same_timer)
        if tmp_same_timer.repeat:
          reset_list.append(tmp_same_timer)
        next_timerid = tmp_same_timer.same_next
      count += tmp_timer.same_count
      
      last_timer = tmp_timer
      count +=1
      tmp_tid = tmp_timer.next
    
    reset_list.reverse()
    memcache.set(key=KEY_RESET_TIMERS_2ND,value=reset_list,time=0,namespace=namespace)
    
    tnum = len(timeout_list)
    if 0<tnum:
      header.count_timeout +=tnum
      header.count -=tnum
      nxt_tid = last_timer.next
      header.first = nxt_tid
      if nxt_tid:
        nxt_timer = timer_map.get(nxt_tid)
        nxt_timer.prev = None
      if not header.first:
        header.last = None
      
      #memcache.set(key=KEY_TIMER_MAP_2ND,value=timer_map_2nd,time=0,namespace=namespace) # // 後ろに移動
    
    for timer in reset_list:
      _reset_timer(timer,sem=False,timer_map_2nd=timer_map_2nd)
    
    # // 更新なしの場合でもmemcacheのリフレッシュのために必ず保存しなおす
    #memcache.set(key=KEY_TIMER_MAP_2ND,value=timer_map_2nd,time=0,namespace=namespace)
    memcache.set(key=KEY_TIMER_MAP_2ND,value=timer_map_2nd,time=3600,namespace=namespace)
    
    memcache.set(key=KEY_RESET_TIMERS_2ND,value=[],time=0,namespace=namespace)
    
    log('check timeout timers: end (namespace=%s)' % (self.namespace))
    self.prn_timer_header()
    
    self._sem_unlock()
    
    return (timeout_list,flg_remain)
  
  def check_and_restore(self):
    namespace = self.namespace
    loginfo('check timer queue (namespace=%s)' % (namespace))
    
    # // 割り切り
    # // - memcache(KEY_TIMER_MAP_2ND)にアクセス出来なければ諦める。
    # // - アクセス出来れば正常と見なす(バグがなければOKのはず…)。
    timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=namespace)
    if not timer_map_2nd: # critical error
      logerr(u'check_and_restore(): timer_map_2nd not found.')
      try:
        self.clear_all_timers()
        timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=namespace)
      except:
        logerr(u'critical situation...abort.')
        return
    
    header = timer_map_2nd.header
    self.prn_timer_header(header)
  
  def prn_timer_header(self,header=None):
    if not header:
      timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=self.namespace)
      if not timer_map_2nd: # critical error
        logerr(u'prn_timer_header(): timer_map_2nd not found.')
        return
      header = timer_map_2nd.header
    hmems=['first','last','count','count_set','count_reset','count_release','count_timeout']
    log(u'[header] (namespace=%s)' % (self.namespace))
    for mem in hmems:
      log(u' %s = %s' % (mem,getattr(header,mem,u'')))
    log('')
  
  def prn_timer(self,timer_map=None,timerid=None,timer=None):
    if timer:
      timerid = timer.timerid
    else:
      if not timerid:
        return
      if not timer_map:
        timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=self.namespace)
        if not timer_map_2nd: # critical error
          logerr(u'prn_timer(): timer_map_2nd not found.')
          return
        timer_map = timer_map_2nd.timer_map
      timerid = str(timerid)
      timer = timer_map.get(timerid)
    
    tmems=['timerid','prev','next','minutes','crontime','tz_hours','timeout','url','user_id','user_info','repeat','same_count','same_prev','same_next']
    log(u' [timer(id=%s)] (namespace=%s)' % (timerid,self.namespace))
    for mem in tmems:
      log(u'  %s = %s' % (mem,getattr(timer,mem,u'')))
    log('')
  
  def prn_timer_short(self,timer_map=None,timerid=None,timer=None):
    if timer:
      timerid = timer.timerid
    else:
      if not timerid:
        return
      if not timer_map:
        timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=self.namespace)
        if not timer_map_2nd: # critical error
          logerr(u'prn_timer_short(): timer_map_2nd not found.',self.namespace)
          return
        timer_map = timer_map_2nd.timer_map
      timerid = str(timerid)
      timer = timer_map.get(timerid)
    
    tmems=['url','user_id','user_info']
    log(u' [timer(id=%s)] (namespace=%s)' % (timerid,self.namespace))
    for mem in tmems:
      log(u'  %s = %s' % (mem,getattr(timer,mem,u'')))
    log('')
  
  def prn_tim_list(self,header=None,timer_map=None,sem=True):
    log(u'prn_tim_list: start (namespace=%s)' % (self.namespace))
    prn_timer = self.prn_timer
    if sem:
      self._sem_lock_retry()
    if not header or not timer_map:
      timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=self.namespace)
      if not timer_map_2nd: # critical error
        logerr(u'prn_tim_list(): timer_map_2nd not found.')
        if sem:
          self._sem_unlock()
        return
      header = timer_map_2nd.header
      timer_map = timer_map_2nd.timer_map
    self.prn_timer_header(header)
    tmp_tid = header.first
    while tmp_tid:
      tmp_timer = timer_map.get(tmp_tid)
      prn_timer(timer_map=timer_map,timer=tmp_timer)
      
      # // 同時タイマチェック
      next_timerid = tmp_timer.same_next
      while next_timerid:
        tmp_same_timer = timer_map.get(next_timerid)
        prn_timer(timer_map=timer_map,timer=tmp_same_timer)
        next_timerid = tmp_same_timer.same_next
      
      tmp_tid = tmp_timer.next
    if sem:
      self._sem_unlock()
    log(u'prn_tim_list: end (namespace=%s)' % (self.namespace))

  def prn_tim_list2(self,header=None,timer_map=None,sem=True):
    log(u'prn_tim_list2: start (namespace=%s)' % (self.namespace))
    if sem:
      try:
        self._sem_lock_retry()
      except:
        self._sem_init()
        self._sem_lock_retry()
    
    if not header or not timer_map:
      timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=self.namespace)
      if not timer_map_2nd: # critical error
        logerr(u'prn_tim_list2(): timer_map_2nd not found.')
        if sem:
          self._sem_unlock()
        return
      header = timer_map_2nd.header
      timer_map = timer_map_2nd.timer_map
    
    self.prn_timer_header(header)
    prn_timer = self.prn_timer
    
    for (timerid,timer) in timer_map.items():
      log(u'<timerid=%s>' % (timerid))
      prn_timer(timer_map=timer_map,timer=timer)
    
    if sem:
      self._sem_unlock()
    
    log(u'prn_tim_list2: end (namespace=%s)' % (self.namespace))
  
  def get_tim_counter(self,header=None,timer_map=None,sem=True):
    log('get timer counter (namespace=%s)' % (self.namespace))
    if sem:
      self._sem_lock_retry()
      
    if not header or not timer_map:
      timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=self.namespace)
      if not timer_map_2nd: # critical error
        logerr(u'get_tim_counter(): timer_map_2nd not found.')
        if sem:
          self._sem_unlock()
        return (None,0,0)
      header = timer_map_2nd.header
      timer_map = timer_map_2nd.timer_map
    
    # // 同時タイマ数カウント
    def _same_count(_tmp_timer):
      scnt=0
      next_timerid = _tmp_timer.same_next
      while next_timerid:
        tmp_same_timer = timer_map.get(next_timerid)
        next_timerid = tmp_same_timer.same_next
        scnt += 1
      return scnt
    
    tmp_tid = header.first
    cnt = 0
    while tmp_tid:
      tmp_timer = timer_map.get(tmp_tid)
      scnt = _same_count(tmp_timer)
      if tmp_timer.same_count!=scnt:
        logerr(u'same timer error(timerid=%s): %d!=%d' % (str(tmp_tid),tmp_timer.same_count,scnt))
      cnt += scnt
      tmp_tid = tmp_timer.next
      cnt += 1
    
    tmp_tid = header.last
    rcnt = 0
    while tmp_tid:
      tmp_timer = timer_map.get(tmp_tid)
      scnt = _same_count(tmp_timer)
      if tmp_timer.same_count!=scnt:
        logerr(u'same timer error(timerid=%s): %d!=%d' % (str(tmp_tid),tmp_timer.same_count,scnt))
      rcnt += scnt
      tmp_tid = tmp_timer.prev
      rcnt += 1
    
    if sem:
      self._sem_unlock()
    
    return (header,cnt,rcnt)
  
  def prn_tim_counter(self):
    (header,cnt,rcnt) = self.get_tim_counter()
    
    self.prn_timer_header(header)
    log(u'count=%d (reverse=%d)' % (cnt,rcnt))

  def save_last_status(self,timerid,last_timeout=u'',last_result=u''):
    memcache.set(key=KEY_STATUS_2ND_BASE+str(timerid),value=dict(last_timeout=last_timeout,last_result=last_result),time=0,namespace=self.namespace)
  
  def get_last_status(self,timerid):
    last_status = memcache.get(key=KEY_STATUS_2ND_BASE+str(timerid),namespace=self.namespace)
    if not last_status:
      last_status = dict(last_timeout=u'',last_result=u'')
    return last_status

  def get_next_time(self,timerid,fmt=DEFAULT_DATETIME_FORMAT):
    next_time = u''
    timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=self.namespace)
    if not timer_map_2nd: # critical error
      logerr(u'get_next_time(): timer_map_2nd not found.')
      return next_time
    timer_map = timer_map_2nd.timer_map
    timer = timer_map.get(str(timerid))
    if timer:
      try:
        next_time = (timer.timeout+timedelta(hours=DEFAULT_TZ_HOURS)).strftime(fmt)
      except:
        next_time = u''
    return next_time
  
  def get_timer_map(self):
    timer_map_2nd = memcache.get(key=KEY_TIMER_MAP_2ND,namespace=self.namespace)
    if not timer_map_2nd: # critical error
      logerr(u'get_timer_map(): timer_map_2nd not found.')
      return {}
    timer_map = timer_map_2nd.timer_map
    if not timer_map:
      timer_map = {}
    return timer_map
  
#} // end of class GAE_Timer2nd()


#{ // def GAE_Timer()
class_GAE_TimerMap={
  '0': GAE_Timer1st,
  '1': GAE_Timer1st,
  '2': GAE_Timer2nd,
}

def GAE_Timer(init=None,namespace=None,def_timeout_path=PATH_DEFAULT_TIMEOUT,ignore_duplicate=True):
  return class_GAE_TimerMap[get_namespace_version(namespace)](
    init=init,
    namespace=namespace,
    def_timeout_path=def_timeout_path,
    ignore_duplicate=ignore_duplicate,
  )
#} // end of GAE_Timer()


#{ // def get_timer_namespace_by_string()
get_timer_namespace_by_string = GAE_Timer(namespace=TIMER_NAMESPACE_NEWEST_DEFAULT).get_timer_namespace_by_string
#} // end of def get_timer_namespace_by_string()


#{ // def get_timer_namespace_by_number()
get_timer_namespace_by_number = GAE_Timer(namespace=TIMER_NAMESPACE_NEWEST_DEFAULT).get_timer_namespace_by_number
#} // end of def get_timer_namespace_by_number()


#{ // def timer_maintenance()
def timer_maintenance():
  def _wrapper(namespace):
    gae_timer = GAE_Timer(namespace=namespace)
    gae_timer.check_and_restore()
  
  _wrapper(TIMER_NAMESPACE_2ND_DEFAULT)
  for ci in range(1,1+MAX_TIMER_TASK_NUMBER):
    _wrapper(TIMER_NAMESPACE_2ND_BASE+str(ci))
  
  _wrapper(TIMER_NAMESPACE_DEFAULT)
  for ci in range(1,1+MAX_TIMER_TASK_NUMBER):
    _wrapper(TIMER_NAMESPACE_BASE+str(ci))

#} // end of def timer_maintenance()


#{ // def timer_initialize()
def timer_initialize():
  def _wrapper(namespace):
    gae_timer = GAE_Timer(namespace=namespace)
    gae_timer.clear_all_timers()
  
  _wrapper(TIMER_NAMESPACE_2ND_DEFAULT)
  for ci in range(1,1+MAX_TIMER_TASK_NUMBER):
    _wrapper(TIMER_NAMESPACE_2ND_BASE+str(ci))
  
  _wrapper(TIMER_NAMESPACE_DEFAULT)
  for ci in range(1,1+MAX_TIMER_TASK_NUMBER):
    _wrapper(TIMER_NAMESPACE_BASE+str(ci))
  
#} // end of def timer_initialize()


#{ // def prn_timer_headers()
def prn_timer_headers():
  def _wrapper(namespace):
    gae_timer = GAE_Timer(namespace=namespace)
    gae_timer.prn_timer_header()
  
  _wrapper(TIMER_NAMESPACE_2ND_DEFAULT)
  for ci in range(1,1+MAX_TIMER_TASK_NUMBER):
    _wrapper(TIMER_NAMESPACE_2ND_BASE+str(ci))
  
  _wrapper(TIMER_NAMESPACE_DEFAULT)
  for ci in range(1,1+MAX_TIMER_TASK_NUMBER):
    _wrapper(TIMER_NAMESPACE_BASE+str(ci))
  
#} // end of def prn_timer_headers()


#{ // def get_maintenance_mode()
def get_maintenance_mode():
  try:
    flg = memcache.get(key=KEY_MAINTENANCE_MODE,namespace=TIMER_NAMESPACE_NEWEST_DEFAULT)
  except:
    flg = False
  if flg:
    maintenance_mode = True
    log(u'*** maintenance_mode = ON  ***')
  else:
    maintenance_mode = False
    log(u'*** maintenance_mode = OFF ***')
  return maintenance_mode
#} // end of def get_maintenance_mode()


#{ // def set_maintenance_mode()
def set_maintenance_mode(flg=False):
  if flg:
    maintenance_mode = True
    loginfo(u'*** set maintenance_mode flag ***')
  else:
    maintenance_mode = False
    loginfo(u'*** reset maintenance_mode flag ***')
  try:
    memcache.set(key=KEY_MAINTENANCE_MODE,value=maintenance_mode,time=0,namespace=TIMER_NAMESPACE_NEWEST_DEFAULT)
  except:
    pass
  return maintenance_mode
#} // end of set_maintenance_mode()


#{ // class timercycle()
class timercycle(webapp.RequestHandler):
  def get(self):
    (req,rsp) = (self.request,self.response)
    
    rsp.set_status(200)
    
    if get_maintenance_mode():
      loginfo(u'*** maintenance mode ***')
      rsp.headers['Content-Type']=CONTENT_TYPE_PLAIN
      rsp.out.write(u'maintenance mode')
      return
    
    try:
      call_num = int(req.get('num','1'))
    except:
      call_num = 1
    
    is_2nd = req.get('2nd',u'')
    
    nsid = req.get('nsid',u'')
    
    if is_2nd:
      namespace = TIMER_NAMESPACE_2ND_BASE + nsid
    else:
      namespace = TIMER_NAMESPACE_BASE + nsid
    
    if namespace==TIMER_NAMESPACE_DEFAULT and call_num==1:
      try:
        taskqueue.add(url=PATH_CYCLE+'?2nd=1',method='GET',headers={'X-AppEngine-TaskRetryCount':0})
      except Exception, s:
        logerr(' => taskqueue error: %s' % (str(s)))
        pass
      for ci in range(1,1+MAX_TIMER_TASK_NUMBER):
        try:
          _url=PATH_CYCLE+'?nsid=%d' % (ci)
          log('call nsid=%d' % (ci))
          taskqueue.add(url=_url,method='GET',headers={'X-AppEngine-TaskRetryCount':0})
        except Exception, s:
          logerr(' => taskqueue error: %s' % (str(s)))
          pass
    elif namespace==TIMER_NAMESPACE_2ND_DEFAULT and call_num==1:
      for ci in range(1,1+MAX_TIMER_TASK_NUMBER):
        try:
          _url=PATH_CYCLE+'?2nd=1&nsid=%d' % (ci)
          log('call nsid=%d' % (ci))
          taskqueue.add(url=_url,method='GET',headers={'X-AppEngine-TaskRetryCount':0})
        except Exception, s:
          logerr(' => taskqueue error: %s' % (str(s)))
          pass
    
    gae_timer = GAE_Timer(namespace=namespace)
    #curtime_str = (utcnow()+timedelta(hours=DEFAULT_TZ_HOURS)).strftime(DEFAULT_DATETIME_FORMAT)
    curtime_str = (gae_timer.curtime+timedelta(hours=DEFAULT_TZ_HOURS)).strftime(DEFAULT_DATETIME_FORMAT)
    
    log(u'timercycle: %s (namespace=%s call number=%d)' % (curtime_str,namespace,call_num))
    
    (timeoutlist,flg_remain) = gae_timer.get_timeout_list(max_num=MAX_TIMEOUT_NUM)
    
    prn_timer_short = gae_timer.prn_timer_short
    
    urls = {}
    def callback(timer,result):
      timerid = timer.timerid
      log(u'callback(timerid=%s): "%s"' % (timerid,urls[timerid]))
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
      
      gae_timer.save_last_status(timerid=timerid,last_timeout=curtime_str,last_result=s_result)
      
      log(s_result)
      #gae_timer.prn_timer_short(timer=timer) # NG(?)
    
    def_url = re.sub(u'^([^:]+://[^/]*).*$',r'\1',req.url)+gae_timer.get_def_timeout_path()
    
    str_rsp = 'timercycle: complete'
    
    while flg_remain:
      call_num += 1
      if MAX_CALL_NUM < call_num:
        str_rsp = 'timercycle: stop(max number(%d) called)' % (MAX_CALL_NUM)
        break
      if is_2nd: # [2010/10/19]条件追加
        _url = PATH_CYCLE+'?2nd=1&nsid=%s&num=%d' % (nsid,call_num)
      else:
        _url = PATH_CYCLE+'?nsid=%s&num=%d' % (nsid,call_num)
      log('  timeout timers left => call taskqueue (%s)' % (_url))
      try:
        taskqueue.add(url=_url,method='GET',headers={'X-AppEngine-TaskRetryCount':0})
        str_rsp = 'timercycle: continue'
        break
      except Exception, s:
        logerr(' => taskqueue error: %s' % (str(s)))
        pass
      break
    
    rpcs = []
    for timer in timeoutlist:
      gae_timer.prn_timer_short(timer=timer) # OK(?)
      timerid = timer.timerid
      url = timer.url
      if url:
        params = None
      else:
        url = def_url
        params = {'timerid':timerid}
        if timer.user_id != None:
          params['user_id'] = timer.user_id
        if timer.user_info != None:
          params['user_info'] = timer.user_info
      
      urls[timerid] = url
      log(u'call(timerid=%s): "%s"' % (timerid,url))
      
      if SAVE_CALLBACK_RESULT:
        rpc = fetch_rpc(url=url,method='GET',params=params,keyid=timer,callback=callback)
      else:
        rpc = fetch_rpc(url=url,method='GET',params=params,keyid=timer)
      if rpc:
        rpcs.append(rpc)
    
    if RPC_WAIT:
      for rpc in rpcs:
        rpc.wait()
    
    log(str_rsp)
    rsp.headers['Content-Type']=CONTENT_TYPE_PLAIN
    rsp.out.write(str_rsp)

#} // end of class timercycle()


#{ // def timer_req_work()
def timer_req_work(self,task_name,do_by_ns,is_2nd):
  (req,rsp) = (self.request,self.response)
  
  rsp.set_status(200)
  
  def _wrapper(namespace):
    loginfo(u'%(task_name)s: called (namespace=%(namespace)s)' % dict(task_name=task_name,namespace=namespace))
    do_by_ns(namespace)
  
  nsid = req.get('nsid',u'')
  if nsid != u'':
    if is_2nd:
      _wrapper(TIMER_NAMESPACE_2ND_BASE+nsid)
    else:
      _wrapper(TIMER_NAMESPACE_BASE+nsid)
    log(u'')
  else:
    if is_2nd:
      _wrapper(TIMER_NAMESPACE_2ND_DEFAULT)
    else:
      _wrapper(TIMER_NAMESPACE_DEFAULT)
    log(u'')
    for ci in range(1,1+MAX_TIMER_TASK_NUMBER):
      if is_2nd:
        _wrapper(TIMER_NAMESPACE_2ND_BASE+str(ci))
      else:
        _wrapper(TIMER_NAMESPACE_BASE+str(ci))
      log(u'')
  
  rsp_str = u'%(task_name)s: end' % dict(task_name=task_name)
  loginfo(rsp_str)
  rsp.headers['Content-Type']=CONTENT_TYPE_PLAIN
  rsp.out.write(rsp_str.encode('utf-8'))
  
#} // end of def timer_req_work()


#{ // class showlist()
class showlist(webapp.RequestHandler):
  def get(self):
    (req,rsp) = (self.request,self.response)
    
    def do_by_ns(namespace):
      gae_timer = GAE_Timer(namespace=namespace)
      gae_timer.prn_tim_list()
    
    timer_req_work(self,'showlist',do_by_ns,req.get('2nd'))

#} // end of class showlist()


#{ // class showlist2()
class showlist2(webapp.RequestHandler):
  def get(self):
    (req,rsp) = (self.request,self.response)
    
    def do_by_ns(namespace):
      gae_timer = GAE_Timer(namespace=namespace)
      gae_timer.prn_tim_list2()
    
    timer_req_work(self,'showlist2',do_by_ns,req.get('2nd'))

#} // end of class showlist2()


#{ // class showcounter()
class showcounter(webapp.RequestHandler):
  def get(self):
    (req,rsp) = (self.request,self.response)
    
    def do_by_ns(namespace):
      gae_timer = GAE_Timer(namespace=namespace)
      gae_timer.prn_tim_counter()
    
    timer_req_work(self,'showcounter',do_by_ns,req.get('2nd'))

#} // end of class showcounter()


#{ // class restore()
class restore(webapp.RequestHandler):
  def get(self):
    (req,rsp) = (self.request,self.response)
    
    def do_by_ns(namespace):
      gae_timer = GAE_Timer(namespace=namespace)
      gae_timer.check_and_restore()
    
    timer_req_work(self,'restore',do_by_ns,req.get('2nd'))

#} // end of class restore()


#{ // class clearall()
class clearall(webapp.RequestHandler):
  def _common(self):
    (req,rsp) = (self.request,self.response)
    
    def do_by_ns(namespace):
      gae_timer = GAE_Timer(namespace=namespace)
      gae_timer.clear_all_timers()
      gae_timer.prn_timer_header()
    
    timer_req_work(self,'clearall',do_by_ns,req.get('2nd'))
  
  def get(self):
    self._common()
  
  def post(self):
    self._common()

#} // end of class clearall()


#{ // class def_timeout()
class def_timeout(webapp.RequestHandler):
  def get(self):
    (req,rsp) = (self.request,self.response)
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


#{ // def main()
def main():
  logging.getLogger().setLevel(DEBUG_LEVEL)
  application = webapp.WSGIApplication([
    (PATH_CYCLE, timercycle),
    (PATH_SHOWLIST, showlist),
    (PATH_SHOWLIST2, showlist2),
    (PATH_SHOWCOUNTER, showcounter),
    (PATH_RESTORE, restore),
    (PATH_CLEARALL, clearall),
    (PATH_DEFAULT_TIMEOUT, def_timeout),
  ],debug=DEBUG_FLAG)
  wsgiref.handlers.CGIHandler().run(application)
#} // end of def main()

if __name__ == "__main__":
  main()

"""
#==============================================================================
# 更新履歴
#==============================================================================
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

"""
#■ end of file
