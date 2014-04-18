(function(){
var	w=window,d=w.document;

var	XHRexec=(function(){
	var	getXHR=(function(){
		if (typeof ActiveXObject!="undefined") {
			var	msXml=['Msxml2.XMLHTTP','Microsoft.XMLHTTP'];
			for (var ci=0,len=msXml.length; ci<len; ci++) with ({msXml:msXml[ci]}) { try {new ActiveXObject(msXml);return function(){return new ActiveXObject(msXml)};} catch(e){} }
			return function(){return null};
		}
		else if (typeof XMLHttpRequest!="undefined") {
			return function(){return new XMLHttpRequest()};
		}
		else {
			return function(){return null};
		}
	})();
	return function(opt){
		var	xh=getXHR();
		if (!xh) return;
		var	async=(opt.async===false)?false:true;
		var	method=opt.method;
		if (!method) method='GET';
		method=method.toUpperCase();
		var	url=opt.url;
		var	headers=opt.headers;
		var	params=opt.params;
		var	data=(opt.data)?opt.data:'';
		if (!data&&params) {
			var	pstrs=[];
			for (var mem in params) {
				if (!params.hasOwnProperty(mem)) continue;
				pstrs[pstrs.length]=mem+'='+encodeURIComponent(params[mem]);
			}
			if (method=='POST') {
				data=pstrs.join('&');
			}
			else {
				url=url+'?'+pstrs.join('&');
			}
		}
		try {xh.open(method,url,async);} catch(e) {if (typeof opt.onerror=='function') opt.onerror(xh);return;}
		if (headers) {
			for (var mem in headers) {
				if (!headers.hasOwnProperty(mem)) continue;
				try {xh.setRequestHeader(mem,headers[mem])} catch(e){};
			}
		}
		if (method=='POST'&&data) xh.setRequestHeader('Content-Type','application/x-www-form-urlencoded');
		var	callback=function(timeout){
			if (timeout) {
				if (typeof opt.ontimeout=='function') {
					opt.ontimeout(xh);
				}
				else if (typeof opt.onerror=='function') {
					opt.onerror(xh);
				}
			}
			else if ((200<=xh.status&&xh.status<300)||xh.status==0) {
				if (typeof opt.onload=='function') opt.onload(xh);
			}
			else {
				if (typeof opt.onerror=='function') opt.onerror(xh);
			}
			try {delete xh;} catch(e) {xh=null;}
		};
		if (async) {
			var	tid=null;
			if (opt.timeout) {
				tid=setTimeout(function(){
					xh.onreadystatechange=function(){};
					try {xh.abort();} catch(e) {}
					callback(true);
				},1000*opt.timeout);
			}
			xh.onreadystatechange=function(){
				if (xh.readyState!=4) return;
				if (tid) clearTimeout(tid);
				setTimeout(function(){callback(false)},1);
			};
		}
		xh.send(data);
		if (!async) {
			callback(false);
		}
	};
})();	//	end of XHRexec()
	
var	setEventHandler=(function(){
	if (w.addEventListener) {
		return function(obj,evt,handler){obj.addEventListener(evt,handler,false)};
	}
	else if (w.attachEvent) {
		return function(obj,evt,handler){obj.attachEvent('on'+evt,handler)};
	}
	else {
		return function(obj,evt,handler){var org=obj['on'+evt];obj['on'+evt]=function(){if(typeof org=='function')org();handler()}};
	}
})();	//	end of setEventHandler()

var	getElementsByTagAndClassName=(function(){
	var	splitClassName=function(className){
		return className.replace(/\s+/g,' ').replace(/(^\s|\s$)/g,'').split(' ');
	};
	return function(tagName,className,doc) {
		if (!doc) doc=d;
		var children=doc.getElementsByTagName(tagName);
		if (className) {
			var	chkElms=(typeof className=='string')?splitClassName(className):className;
			var	flgElms=[];
			for (var ci=0,len=chkElms.length; ci<len; ci++) flgElms[chkElms[ci]]=true;
			var elements=[];
			for (var ci=0,leni=children.length; ci<leni; ci++) {
				var child=children[ci];
				var cname=child.className;
				if (!cname) continue;
				var cnameElms=splitClassName(cname);
				for (var cj=0,lenj=cnameElms.length; cj<lenj; cj++) {
					if (flgElms[cnameElms[cj]]) {
						elements[elements.length]=child;
						break;
					}
				}
			}
			return elements;
		}
		else {
			return children;
		}
	};
})();	//	end of getElementsByTagAndClassName()

var	change_screen_mask=function(flg){
	var	mask=d.getElementById('mask');
	mask.style.display = (flg)?'block':'none';
};	//	end of change_screen_mask()

var	getInputParams=function(form){
	change_screen_mask(true);
	var	params={};
	var	inputs=form.getElementsByTagName('input');
	for (var ci=0,len=inputs.length; ci<len; ci++) {
		var	input=inputs[ci];
		//input.disabled='disabled';
		if (input.type=='radio') {
			if (input.checked) params[input.name] = input.value;
		}
		else {
			params[input.name]=input.value;
		}
	}
	return params;
};	//	end of getInputParams()

var	resumeInputParames=function(form){
	var	inputs=form.getElementsByTagName('input');
	for (var ci=0,len=inputs.length; ci<len; ci++) {
		var	input=inputs[ci];
		//input.disabled='';
		input.blur();
	}
	change_screen_mask(false);
};	//	end of resumeInputParames()

var	cycle_names=['cycle'],cron_names=['min','hour','day','month','wday','tz_hours'];
var	suspend=w.suspend=function(input,kind){
	var	form=input.form;
	if (kind=='cycle') var hnames=cycle_names, vnames=cron_names;
	else var hnames=cron_names, vnames=cycle_names;
	for (var ci=0,len=hnames.length; ci<len; ci++) {
		var	elm = form[hnames[ci]]
		//elm.disabled=true;
		elm.readOnly=true;
		elm.style.backgroundColor='#cccccc';
	}
	for (var ci=0,len=vnames.length; ci<len; ci++) {
		var	elm = form[vnames[ci]]
		//elm.disabled=false;
		elm.readOnly=false;
		elm.style.backgroundColor='white';
	}
};	//	end of suspend()

var	modify_form=function(form){
	var	inputs=form.getElementsByTagName('input');
	for (var ci=0,len=inputs.length; ci<len; ci++) {
		var	input=inputs[ci];
		if (input.name=='kind' && !input.checked) suspend(input,input.value);
	}
};	//	end of modify_form()

w.postcron=(function(){
	var	work=d.createElement('div');
	return function(form){
		var	params=getInputParams(form);
		var	onload=function(xh){
			work.innerHTML=xh.responseText;
			var	new_form=work.getElementsByTagName('form')[0];
			if (new_form) {
				var	pnode=form.parentNode;
				pnode.insertBefore(new_form,form);
				pnode.removeChild(form);
				modify_form(new_form);
			}
			var	unregistered=d.getElementById('unregistered');
			if (unregistered) {
				unregistered.parentNode.removeChild(unregistered);
			}
			change_screen_mask(false);
		};
		var	onerror=function(xh){
			alert('設定に失敗しました');
			resumeInputParames(form);
		};
		params.ajax='1';
		XHRexec({
			method		:	'POST'
		,	url			:	form.action
		,	params		:	params
		,	onload		:	onload
		,	onerror		:	onerror
		,	timeout		:	120
		});
		return false;
	};
})();	//	end of postcron()

w.confirm_unregist=function(form){
	var	result=confirm('登録を削除してよろしいですか？');
	if (result) change_screen_mask(true);
	return result;
};	//	end of confirm_unregist()

w.confirm_restore_timer=function(form){
	var	result=confirm('全ユーザのタイマを再設定してもよろしいですか？');
	if (result) change_screen_mask(true);
	return result;
};	//	end of confirm_restore_timer()

w.initialize=function(){
	var	forms=d.getElementsByTagName('form');
	for (var ci=0,len=forms.length; ci<len; ci++) {
		modify_form(forms[ci]);
	}
};	//	end of initialize()

w.trial=function(form){
	change_screen_mask(true);
	var	params={
		trial	:	'1'
	,	url		:	form.timerinfo_url.value
	};
	var	trial_status=getElementsByTagAndClassName('div','trail_status',form)[0];
	var	onload=function(xh){
		trial_status.innerHTML='<b>試行結果：'+xh.responseText+'</b>';
		change_screen_mask(false);
	};
	var	onerror=function(xh){
		if (xh.status==400) {
			trial_status.innerHTML='<b>試行結果：<span style="color:red;">'+xh.responseText+'</span></b>';
		}
		else {
			alert('試行失敗しました');
		}
		change_screen_mask(false);
	};
	XHRexec({
		method		:	'GET'
	,	url			:	form.action
	,	params		:	params
	,	onload		:	onload
	,	onerror		:	onerror
	,	timeout		:	120
	});
};	//	end of trial()

})();
