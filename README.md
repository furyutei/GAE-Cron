GAE-Cron
========
Google App Engine上で動作する簡易 web cron サービス  
version 0.0.3  
　powered by Google App Engine  
　License: The MIT license  
　Copyright (c) 2010-2014 風柳(furyu)  

+ [ブログ： 風柳メモ](http://d.hatena.ne.jp/furyu-tei/)  
+ [Twitter： @furyutei](http://twitter.com/furyutei)  

■ なにこれ？
---
  あらかじめURLとタイマとを設定しておくと、周期的にURLを叩いてくれる(GETメソッドでコールする)、簡易的なweb cronサービスです。  
  Google App Engine(GAE)上で動作します。

+ 複数のユーザ（デフォルトでは50人まで）で共用可能です（利用には[Googleアカウントが必要](https://www.google.com/accounts/NewAccount?hl=ja)です)。
+ 各ユーザは独立して複数個のタイマを設定できます（デフォルトでは3個まで）。
+ 周期タイマを分単位で設定可能です（ただし、周期が短いとそれだけ負荷がかかり、リソースを多く消費します）。


■ 自分でサービスを立てられるの？
---
  全ソースコードを公開していますので、[Google App Engine](http://code.google.com/intl/ja/appengine/)に[登録](https://appengine.google.com/)後、ソースをアップロード(デプロイ)することで、どなたでもサービスを動かすことが出来ます。
  
+ (リソース制限はありますが、Free Quotaの範囲であれば)無料で使用できます。
+ Google アカウントが必要ですので、予め[作成しておいてください](https://www.google.com/accounts/NewAccount?hl=ja)。
+ Google App Engineへの登録には、メールが送受信できる携帯電話が必要です。


■ 必要なものは？
---
UTF-8が編集出来るテキストエディタと、Python 2.7.x、それにGoogle App Engine SDK（GAE/Pythonの開発キット）が必要となります。

### テキストエディタ ###
文字コードとしてUTF-8が使用可能なテキストエディタであれば、特に制限はありません。  
[無料で使えるエディタもあります](http://techacademy.jp/magazine/986)ので、お好みのものをお使いください。

### Python ###
Python は、[Our Downloads | Python.org](https://www.python.org/downloads/) から、開発環境(OS)にあった 2.7.x 系をダウンロードして、インストールして下さい。  

+ 2014/06/10 現在、[Python 2.7.7 (June 1, 2014)](https://www.python.org/download/releases/2.7.7/) が最新のようです。ただ、[最新版を使うと思わぬエラーが出ることもあるようです](http://d.hatena.ne.jp/thinkAmi/20140402/1396389280)。問題があるようなら、[2.7.5](https://www.python.org/download/releases/2.7.5/)をお試しください。
+ Python には他の系列（2.5.x、2.6.x 、3.x.x 等）もありますが、こちらだと Google App Engine SDK が対応していないため、***必ず 2.7.x 系を使用するように***して下さい。

### Google App Engine SDK ###
SDK は、[Download the Google App Engine SDK - Google App Engine ? Google Developers](https://developers.google.com/appengine/downloads?hl=ja)の Google App Engine SDK for Python（三角形をクリックするとダウンロード用のリンク等が表示されます）を開発環境(Windows、Mac OS X、Linux/Other Platforms）に応じてダウンロードし、インストールして下さい。  
※ SDK は頻繁に更新されます。なるべく最新のものをご使用願います。

### 参考 ###
GAE/Python の開発やデプロイについての詳細は、

+ [Python Runtime Environment - Google App Engine ? Google Developers](https://developers.google.com/appengine/docs/python/?hl=ja)
+ [Google App Engineへの登録と開発環境のセットアップ（Python編）](http://d.hatena.ne.jp/furyu-tei/20100115/gaeregister)
+ [『GAE-Cron』のソース＆サービス登録サイト公開](http://d.hatena.ne.jp/furyu-tei/20100115/gaecronclub)

などを参照して下さい。


■ ファイル構成
---
  GAE-Cron のファイル構成は以下のようになっています。

    GAE-Cron
      +-- README.md
      +-- LICENSE
      +-- app.yaml.sample
      +-- cron.yaml.sample
      +-- gaecron.yaml.sample
      +-- gaecron.py
      +-- gaetimer.py
      +-- index.yaml
      +-- appengine_config.py
      +-- template
      |     +-- gc-top.html
      |     +-- gc-user-header.html
      |     +-- gc-user-form.html
      |     +-- gc-user-footer.html
      |     +-- status.html
      +-- css
      |     +-- gc-common.css
      |     +-- status.css
      +-- script
      |     +-- gaecron.js
      +-- image
            +-- favicon.ico
            +-- profile_s.gif
            +-- appengine-noborder-120x30.gif
  
  
  後で説明する箇所の修正が完了したら、ネット上にアップロード(デプロイ)します。
  
  Windows 7の場合、例えば  
  C:\GAE\GAE-Cron  
  に展開したとすると、Google App Engine Launcher の  
  File → Add Existing Application... Ctrl+Shift+N の Application PATH に  
  C:\GAE\GAE-Cron  
  を指定してやり、その後、[Deploy]を押してアップロード(デプロイ)します。
  
  なお、Google App Engine Launcher は、デフォルトでは  
  C:\Program Files (x86)\Google\google_appengine\launcher\GoogleAppEngineLauncher.exe  
  にあります（デスクトップ上にショートカットも出来ると思います）。


■ 設定ファイル(*.yaml)のコピー
---
  "*.yaml.sample" というファイルは、".sample" を除去したファイル名でコピー後、ご自分の環境に合わせて編集・保存してお使いください。

+ app.yaml.sample → app.yaml
+ cron.yaml.sample → cron.yaml
+ gaecron.yaml.sample → gaecron.yaml
  
  なお、 version 0.02* からのバージョンアップの場合、

- cron.yaml および gaecron.yaml については、そのまま使用できます。
- app.yaml は Python 2.5 → 2.7 に runtime が変更となっている関係上そのままでは使用できません。


■ 設定ファイルで変更必須の箇所
---
### app.yaml ###
  一番最初の行が

     application: gaecron

  となっていますが、この'gaecron' を自分でGoogleから取得したアプリケーション名(Application Identifier:appid)に変更して下さい。
    
  基本的にはこれだけを変更後、Google App Engine にデプロイすれば動作開始します。  
  http://(appid).appspot.com/  
  にアクセスすることで、GAE-Cronのトップページにアクセス出来ます。  


■ 登録可能数を変更したい場合
---
### gaecron.yaml ###

    # MaxUser: 最大ユーザ数
    MaxUser : 50

  及び

    # MaxTimerPerUser: 1ユーザあたりの最大タイマ数
    MaxTimerPerUser : 5

  を適当に変更して下さい。
    
  ただし、増やすとそれだけ負荷が高くなり、CPUリソースを使い切って "Over Quota" となってしばらく何もできなくなる場合もあるので、充分ご注意下さい。
  

■ PATH を変更したい場合
---
  他のアプリと併用するときなど、トップページのパスを変更したい場合に修正する箇所を示します。

  ここでは、トップページを  
  http://(appid).appspot.com/gc/  
  に変更する場合を例に説明します。  
  
### app.yaml ###

    - url: /(check|restore)_timer.*
      script: gaecron.app
      login: admin

  とある箇所を

    - url: /gc/(check|restore)_timer.*
      script: gaecron.app
      login: admin

  に、

    - url: /.*
      script: gaecron.app
  
  とある箇所を

    - url: /gc/.*
      script: gaecron.app
  
  に、それぞれ変更します。

### gaecron.py ###
    PATH_BASE = u''               # 基準となるPATH(u''はルート)

  とある箇所を、

    PATH_BASE = u'/gc'            # 基準となるPATH

  に変更します。


■バージョンアップ時の処理
---
### アップロード(デプロイ)用ファイルの上書き ###
  
  ファイルを全て上書きしてからデプロイして下さい。

  ただし、*.yaml 等の設定ファイルや、旧バージョンでソースコード中のPATH 等を変更している場合、前の設定をメモしておき、同様の変更を施してからデプロイするようにしてください。
  

### 全タイマの再設定 ###
     
  管理者権限でログインし、画面左上部にある[全タイマ再設定]ボタンを押します。

  基本的には、どのversionからの移行でも実施する必要があります。  
  ただし、0.02*から移行時には、うまく行けば再設定しなくてもいいかもしれません（それでも、うまくいってなさそうなときはやはり実施が必要です）。

  この操作を実施するとタイマがリセットされるため、特に長い周期のタイマを設定している人には影響が大きいと思われますが、今のところ対処の予定はありません。


■ Google App Engineの正式サービス開始に伴う影響について
---
### 概要 ###
  Google App Engineは2011年11月(?)にPreviewを卒業し、正式サービスに移行、新料金体系が適用されるようになりました。  
  これに伴い、Free Quota（無料で使用可能なリソース）の範囲が大幅に狭まり、改定前には問題無くGAE-Cronが動作していた場合でも、不具合が生じる（"Over Quota"が発生する等）場合があります。  
  ※主に影響するのは、管理画面の Dashboard 等で表示される "Frontend Instance Hours" です。"Over Quota"が出るような場合、ここのバーが赤く、100%になっていると思います。

### 対策 ###
  Google App Engine の管理画面で、  
    Administration > Application Settings > Performance
  とたどっていくと、"Max Idle Instances" と "Min Pending Latency" というふたつのスライダがありますが、

+ "Max Idle Instances" を "Automatic" から "1" に下げる（左・Min方向にずらす）
+ "Min Pending Latency" を "Automatic" から "15s" に上げる（右・Max方向にずらす）
  
  とし、[Save Settings]をクリックして保存することにより、パフォーマンスは低下するものの、使用するリソース(Frotend Instance Hours)を低く抑えることが出来ます。   
  ※これで確実に解消される保証はありません。

  上記対策を行っても改善されない場合、著者（風柳）の方で対応するのは困難です。  
  「課金を払う」「タイマ数／ユーザ数を減らす」「ソースをご自分で改修して対応」「諦める」  
  など、ご利用されている方のご判断で対処をお願いします。
  
### 参考 ###
+ [App Engine Pricing - Google App Engine ? Google Developers](https://developers.google.com/appengine/pricing)
+ [GAE-Cronのバージョンアップの前に：Google App Engineの設定変更のススメ](http://d.hatena.ne.jp/furyu-tei/20110923/gaecron)
+ [App Engine の料金体系変更に関する FAQ - Google Developer Relations Japan Blog](http://googledevjp.blogspot.jp/2011/07/app-engine-faq.html)
+ [Google App Engine Blog: The Year Ahead for Google App Engine!](http://googleappengine.blogspot.com/2011/05/year-ahead-for-google-app-engine.html)
+ [Google App Engine Blog: A few adjustments to App Engine’s upcoming pricing changes](http://googleappengine.blogspot.com/2011/09/few-adjustments-to-app-engines-upcoming.html)
