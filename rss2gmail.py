#!/usr/bin/python
"""rss2gmail: get RSS feeds emailed to you
https://github.com/AndroKev/rss2gmail

Original Idee: http://rss2email.infogami.com
Forked from: https://github.com/rcarmo/rss2imap
"""
__version__ = "0.9"
__author__ = "AndroKev"
__copyright__ = "(C) 2004 Aaron Swartz. GNU GPL 2 or 3."
___contributors__ = ["Dean Jackson", "Brian Lalor", "Joey Hess",
                     "Matej Cepl", "Martin 'Joey' Schulze",
                     "Marcel Ackermann (http://www.DreamFlasher.de)",
                     "Rui Carmo (http://taoofmac.com)",
                     "Lindsey Smith (maintainer)", "Erik Hetzner",
                     "Aaron Swartz (original author)", "rcarmo"]

### Import Modules ###

import os, sys, time
import argparse
from datetime import datetime, timedelta

import imaplib
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import feedparser

feedparser.USER_AGENT = "rss2gmail/" + __version__ + " +https://github.com/AndroKev/rss2gmail"
VALID_CHAR = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
DEFAULT_IMAP_FOLDER = "INBOX"
VERBOSE=False
warn = sys.stderr

### Mail Functions ###

def send(author, subject, published, labels, content, mail=None):
    if not mail:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(GMAIL_USER, GMAIL_PASS)
        except Exception:
            print >>warn, "Counld't login into account, please check login-deatails!"
            sys.exit(1)

    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From']    = author
    msg['To']      = GMAIL_USER
    msg.attach(MIMEText(content, 'html'))

    mail.create(MAIN_GMAIL_FOLDER)
    rv, data = mail.append(MAIN_GMAIL_FOLDER, "", published, msg.as_string())
    num=data[0].split(' ')[2][:-1]
    if rv == "OK":
        for label in labels:
            mail.select(MAIN_GMAIL_FOLDER)
            mail.uid('STORE', num, '+X-GM-LABELS', "%s/%s" % (MAIN_GMAIL_FOLDER, label))
    return mail

def delete_read(mail=None):
    if mail:
        if DELETE_READ_AFTER_DAYS != 0:
            mail.select(MAIN_GMAIL_FOLDER)
            yesterday = (datetime.now() - timedelta(days=DELETE_READ_AFTER_DAYS)).strftime("%d-%b-%Y")
            res, data = mail.search(None, '(SEEN BEFORE %s UNFLAGGED)' % yesterday)
            if res == 'OK':
                    items = data[0].split()
                    for i in items:
                        res, data = mail.fetch(i, "(UID)")
                        if data[0]:
                            u = data[0].split(' ')[2][:-1] # get uid
                            res, data = mail.uid('COPY', u, '[Gmail]/Papierkorb')
                            if res == 'OK':
                                res, data = mail.uid('STORE', u, '+FLAGS', '\\Deleted')
                                mail.expunge()

### Utility Functions ###

class InputError(Exception): pass

def isstr(f): return isinstance(f, type('')) or isinstance(f, type(u''))
def ishtml(t): return type(t) is type(())
def contains(a,b): return a.find(b) != -1

### Parsing Utilities ###

def getContent(entry):

    conts = entry.get('content', [])

    if entry.get('summary_detail', []):
        conts += [entry.summary_detail]

    if conts:
        for c in conts:
            if contains(c.type, 'html'): return ('HTML', c.value)

    return None

def getFromEmail(feed_data, entry, firstlabel):
    value = entry.get('author_detail', firstlabel) #feed.auto_detail fallback?
    url=feed_data['feed'].get('link', None).replace("http://","").replace("https://","").replace("www.","").split('/')[0] # not beautiful, but it worked
    if type(value) is str:
        name=value
        mail="author@%s" % url
    else:
        name = value.get('name', firstlabel)
        mail = value.get('email', "%s@%s" % (name.replace(" ", "."), url ))
    return "%s <%s>" % (name, mail)

### Program Functions ###

def feed_db_save(array):
    os.remove(FEEDFILE_PATH)

    for feed in array:
        with open(FEEDFILE_PATH, 'a') as f:
            line = feed[0]
            for i in feed[1:]:
                line += "; " + str(i)
            f.write("%s\n" % line)

def run(nosend, num=None):
    feeds = _list(True)
    mailserver = None
    mail = None
    try:
        """
        # We store the default to address as the first item in the feeds list.
        # Here we take it out and save it for later.
        default_to = ""
        if feeds and isstr(feeds[0]): default_to = feeds[0]; ifeeds = feeds[1:]
        else: ifeeds = feeds
        """
        if num:
            ifeeds = [feeds[num]]
        else:
            ifeeds = feeds
        feednum = 0

        for f in ifeeds:
            try:
                feednum += 1
                # if VERBOSE: print >>warn, 'I: Processing [%d] "%s"' % (feednum, f[0])
                r = {}
                r = feedparser.parse(f[0], f[2], f[3])
                if r.get('status', None) == 304:
                    if VERBOSE: print "skipped: %s" % f[0]
                    continue

                t = "".join(x for x in f[0] if x in VALID_CHAR)
                path = os.path.join(ARCHIVE_PATH, t)
                seen = open(path, 'r').readlines()

                r.entries.reverse()
                for entry in r.entries:
                    uid = entry.get('id', entry.get('link', entry.get('title', None)))
                    if uid+'\n' in seen:continue
                    # new entry found:
                    title = entry.get('title', None).strip()
                    puplished = entry.get('published_parsed', time.localtime())
                    author = getFromEmail(r, entry, f[4])
                    article_link = entry.get('link', r['feed'].get('link', ""))

                    msg = unicode("""<h1><a href="%s" title="%s">%s</a></h1><br />
                    """ % (article_link, title, title))
                    msg += getContent(entry)[1]

                    if not nosend:
                        mail = send(author, title, puplished, f[4:], msg.encode('ascii', 'xmlcharrefreplace'))

                    with open(path, 'a') as _file:
                        _file.write("%s\n" % uid)

                f[2], f[3] = r.get('etag', None), r.get('modified', None)
            except (KeyboardInterrupt, SystemExit):
                raise
        feed_db_save(ifeeds)

    finally:
        if mail:
            delete_read(mail)
            try:
                mail.close()
            except:
                mail.logout()

def add(add_list):
    valid_char = VALID_CHAR + ".-_/ "

    feeds = _list(True)
    for feed in feeds:
        if feed[0] == add_list[0]:
            print "This feed already exists!"
            exit(1)

    d = feedparser.parse(add_list[0])
    labels = "".join(x for x in d['feed'].get('title', None) if x in valid_char) # get the Mainlabel(websitetitle)
    for l in add_list[1:]: #add the other labels
        labels += "; " + "".join(x for x in l if x in valid_char)
    feeds.append([add_list[0], FULLFEED, d.get('etag', None), d.get('modified', None), labels])
    feed_db_save(feeds)

    if ADD_ARCHIVE_NEW_FEED:
        t = "".join(x for x in add_list[0] if x in VALID_CHAR)
        path = os.path.join(ARCHIVE_PATH, t)
        with open(path, 'a') as f:
            for item in d.get('entries', None):
                f.write("%s\n" % item.get('id', item.get('title', '')))

def _list(array=False): #is also used to load the db!
    feeds = []
    # print("Nr.)  url  labels  fullfeed")
    # print("="*100)
    for index, l in enumerate(open(FEEDFILE_PATH, 'r').readlines(), 1):
        line = l.strip()
        if line != "":
            v = line.split('; ')
            if array:
                feeds.append(v)
            else:
                labels=v[4]
                for l in v[5:]:
                    labels += ", " + l
                print "%s.) %s [%s] %s" %(str(index), v[0].strip(), labels, v[1])
    if array:
        return feeds

def reset(nr):
    nr-=1
    feeds=_list(True)
    if nr < 0:
        print "ID has to be equale to or higher than 1"
    elif nr > len(feeds):
        print "No such Feed"
    else:
        url = feeds[nr][0]
        if url.startswith('#'):
            url = url[2:]
        t = "".join(x for x in url if x in VALID_CHAR)
        path = os.path.join(ARCHIVE_PATH, t)
        if os.path.exists(path):
            os.remove(path)
            print('The feed "%s" was sucessfull reseted!' % url)
        open(path, 'w').close()

def toggleactive(nr, mode):
    nr -= 1
    feeds = _list(True)
    if nr < 0:
        print "ID has to be equale to or higher than 1"
    elif nr >= len(feeds):
        print "No such Feed"
    else:
        feed = feeds[nr]
        if mode:
            if feed[0].startswith('#'):
                feeds[nr][0] = feed[0][2:]
            else:
                print "der angegebene feed war nicht deaktiviert"
        else:
            if not feed[0].startswith('#'):
                # print feeds[nr]
                feeds[nr][0] = "# %s" % feed[0]
            else:
                print "der angegebene feed war nicht aktiviert"

        feed_db_save(feeds)

def delete(nr):
    nr-=1
    feeds = _list(True)
    if nr < 0:
        print "ID has to be equale to or higher than 1"
    elif nr >= len(feeds):
        print "No such Feed"
    else:
        url = feeds[nr][0]
        if url.startswith('#'):
            url = url[2:]
        t = "".join(x for x in url if x in VALID_CHAR)
        path = os.path.join(ARCHIVE_PATH, t)
        if os.path.exists(path):
            os.remove(path)

        del feeds[nr]
        # print feeds
        feed_db_save(feeds)
        print('The feed "%s" was sucessfull deleted!' % url)

def email(addr):
    feeds, feedfileObject = load()
    if feeds and isstr(feeds[0]): feeds[0] = addr
    else: feeds = [addr] + feeds

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-c", "--configfile", help="Path to your config-file", metavar="<file>")
    parser.add_argument("--add", help="Add a Feedurl!", metavar="feedurl LABELS", nargs="+")
    parser.add_argument("--no-send", help="Only load the feed, without sending them", action="store_true")
    parser.add_argument("-l", "--list", action="store_true")
    parser.add_argument("-d", "--delete", help="Delete a Feedurl", metavar="<nr>", type=int)
    parser.add_argument("--reset", help="Reset a Feed-Archive-File", metavar="<nr>", type=int)
    parser.add_argument("--enable", help="Enable a Feed", metavar="<nr>", type=int)
    parser.add_argument("--disable", help="Disable a Feed", metavar="<nr>", type=int)
    parser.add_argument("--verbose", help="Get more information!", action="store_true")
    parser.add_argument("-V", "--version", action='version', version='%(prog)s {version}'.format(version=__version__))
    args = parser.parse_args()

    # Read options from config file if present.

    if args.configfile:
        sys.path.append(os.path.dirname(args.configfile))
    else:
        sys.path.insert(0, ".")
    try:
        from config import *
    except:
        print >>warn, "No config-file found!"
        print >>warn, "Please rename config.py.example to config.py, edit it und try it again!"
        sys.exit(1)

    if not os.path.exists(FEEDFILE_PATH):
        open(FEEDFILE_PATH, "w").close()
    if not os.path.exists(ARCHIVE_PATH):
        os.makedirs(ARCHIVE_PATH)

    if GMAIL_PASS == "" or GMAIL_USER == "":
        print """It seams that you run the tool the first time.
Please edit the config file to your need and start the tool again!"""
    else:
        if args.verbose:
            VERBOSE=True
        if args.list:
            _list()
        elif args.delete >= 0:
            delete(args.delete)
        elif args.enable >= 0:
            toggleactive(args.enable, True)
        elif args.disable >= 0:
            toggleactive(args.disable, False)
        elif args.reset >= 0:
            reset(args.reset)
        elif args.add:
            add(args.add)
        else:
            run(args.no_send)
