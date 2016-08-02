#!/usr/bin/python
# -*- coding: utf-8 -*-

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

# Import Modules

import os
import sys
import time
import re
import argparse
import urllib2

import imaplib
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.header import Header
import feedparser

feedparser.USER_AGENT = "rss2gmail/" + __version__ + " +https://github.com/AndroKev/rss2gmail"
VALID_CHAR = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
DEFAULT_IMAP_FOLDER = "INBOX"
warn = sys.stderr


# Mail Functions

def mail_login():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
        return mail
    except Exception:
        print >>warn, "Couldn't login, please check login-details!"
        sys.exit(1)


def send(author, subject, article_link, published, labels, content, mail=None):

    if not mail:
        mail = mail_login()

    msg = MIMEMultipart('alternative')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = author
    msg['To'] = GMAIL_USER

    if USE_IMAGES >= 0 or SUMMARIZE > 0:
        parser = Parser(tag='img', attr='src')
        parser.feed(content)
        img_nr = 0

        for src in parser.attrs:
            img_nr += 1

            if USE_IMAGES == 0 or SUMMARIZE > 0:
                content = re.sub(r'<img.*src="%s".*?/>' % re.escape(src), '', content)

            elif USE_IMAGES == 2:
                try:
                    if VERBOSE:
                        print "    Load image: %s" % src
                    req = urllib2.Request(src.encode('utf-8'), headers={'User-Agent': 'Mozilla/5.0 (Windows; U; Windows NT 5.1; it; rv:1.8.1.11) Gecko/20071127 Firefox/2.0.0.11'})
                    img_data = urllib2.urlopen(req)
                    try:
                        img = MIMEImage(img_data.read())
                    except:
                        img = MIMEImage(img_data.read(), _subtype="png")
                    # WORKAROUND: because the gmail-android-app dosen't load contend-id-images, it replace the <img/> with an image_name and add the image as an attachment!
                    content = re.sub(r'<img.*src="%s".*?/>' % re.escape(src), 'Bild_%d' % img_nr, content)
                    img.add_header('Content-Disposition', 'attachment; filename="Bild_%d"' % img_nr)
                    msg.attach(img)
                except:
                    print >>warn, "Could not load image: %s" % src.encode('utf-8')
                    pass

    if SUMMARIZE > 0:
        content = summarize(content, SUMMARIZE)

    body = '<h1 class="header"><a href="%s">%s</a></h1>\n' % (article_link, subject)
    body += content

    msg.attach(MIMEText(body, 'html', 'utf-8'))

    mail.create(MAIN_GMAIL_FOLDER)
    rv, data = mail.append(MAIN_GMAIL_FOLDER, "", published, msg.as_string())
    num = data[0].split(' ')[2][:-1]

    if rv == "OK":
        for label in labels:
            mail.select(MAIN_GMAIL_FOLDER)
            mail.uid('STORE', num, '+X-GM-LABELS', "%s/%s" % (MAIN_GMAIL_FOLDER, label))
    return mail


def delete_read(mail=None):

    if not mail:
        mail = mail_login()

    if VERBOSE:
        print "Searching for read mails!"
    mail.select(MAIN_GMAIL_FOLDER)
    res, data = mail.search(None, '(SEEN UNFLAGGED)')
    if res == 'OK':
            for num in data[0].split():
                mail.store(num, '+X-GM-LABELS', '\\Trash')  # with this the mail is moved to trash and after 30day it is deleted!
            mail.expunge()
            print "Deleted %d seen mails!" % len(data[0].split())


# Utility Functions

class InputError(Exception):
    pass


def isstr(f):
    return isinstance(f, type('')) or isinstance(f, type(u''))


def contains(a, b):
    return a.find(b) != -1


def getContent(entry):

    conts = entry.get('content', [])
    conts += [entry.get('summary_detail', [])]
    conts += [entry.get('description', [])]

    if conts:
        for c in conts:
            if contains(c.type, 'html'):
                return c.value


def getFromEmail(feed_data, entry, firstlabel):
    value = entry.get('author_detail', firstlabel)
    tm = str(time.time())

    if type(value) is str:
        name = value
    else:
        name = value.get('name', firstlabel)

    if DEFAULT_EMAIL_FROM:
        mail = DEFAULT_EMAIL_FROM
    else:
        mail = "%s@rss2gmail.com" % tm

    return "\"%s\" <%s>" % (name.encode('utf-8'), mail)


def summarize(text, lenght):
    if len(text) > lenght:
        txt_summarize = ""
        for i in [". ", "? ", "! "]:
            text_summarize = ""
            text_array = text[0:lenght].split(i)[:-1]
            for seq in text_array:
                text_summarize += "%s%s" % (seq, i)
            if len(text_summarize) > len(txt_summarize):
                txt_summarize = text_summarize
        # if txt_summarize == "":
            # return text
        # else:
        return txt_summarize
    else:
        return text


# Program Functions

# HTML Parser for grabbing links and images

from HTMLParser import HTMLParser


class Parser(HTMLParser):
    def __init__(self, tag='a', attr='href'):
        HTMLParser.__init__(self)
        self.tag = tag
        self.attr = attr
        self.attrs = []

    def handle_starttag(self, tag, attrs):
        if tag == self.tag:
            attrs = dict(attrs)
            if self.attr in attrs:
                self.attrs.append(attrs[self.attr])


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
        if num:
            ifeeds = [feeds[num]]
        else:
            ifeeds = feeds

        feednum = 0
        articlenum = 0

        for f in ifeeds:
            # try:
            feednum += 1
            if f[0].startswith('# '):
                print 'I: Skipped    [%d/%d] "%s"' % (feednum, len(ifeeds), f[0][2:])
                continue

            print 'I: Processing [%d/%d] "%s"' % (feednum, len(ifeeds), f[0])
            r = {}
            r = feedparser.parse(f[0], f[1], f[2])
            if r.get('status', None) == 304:
                if VERBOSE:
                    print "  skipped: %s (nothing changed)" % f[0]
                continue

            valid_char = VALID_CHAR + ".-_"
            t = "".join(x for x in f[3] if x in valid_char)
            path = os.path.join(ARCHIVE_PATH, t)

            try:
                for entry in r.entries:
                    seen = open(path, 'r').read().decode('utf-8')
                    uid = entry.get('title', entry.get('link', entry.get('id', None)))

                    if seen.find(uid) != -1:
                        if VERBOSE:
                            print "  skipped: %s (already seen)" % uid
                        continue

                    # new entry found:

                    articlenum += 1
                    if VERBOSE:
                        print "  new article: %s" % uid
                    if not nosend:
                        title = entry.get('title', None).strip()
                        updated = entry.get('updated_parsed', time.localtime())
                        puplished = entry.get('published_parsed', updated)
                        author = getFromEmail(r, entry, f[3])
                        article_link = entry.get('link', r['feed'].get('link', ""))
                        content = getContent(entry)

                        mail = send(author, title, article_link, puplished, f[3:], content, mail)

                    with open(path, 'a') as _file:
                        _file.write("%s\n" % uid.encode('utf-8'))
                        _file.close()
            except Exception as e:
                print >>warn, "There was an Error on entry %s on Feed: %s" % (entry, f[0])
                print >>warn, e
                continue

            f[1], f[2] = r.get('etag', None), r.get('modified', None)

        print 'Found %d new articles!' % articlenum
        feed_db_save(ifeeds)

    finally:
        if mail:
            delete_read(mail)
            try:
                mail.close()
            except:
                mail.logout()


def add(add_list):
    feeds = _list(True)

    for feed in feeds:
        if feed[0] == add_list[0]:
            print "ERROR: '%s' already exists!" % add_list[0]
            exit(1)

    try:
        d = feedparser.parse(add_list[0])
        main_label = d['feed'].get('title', d['feed'].get('link', add_list[0])).strip()
        valid_char = VALID_CHAR + ".-_/ "
        labels = "".join(x for x in main_label if x in valid_char)  # get the Mainlabel(websitetitle)

        for l in add_list[1:]:  # add the other labels
            labels += "; " + "".join(x for x in l if x in valid_char)

        feeds.append([add_list[0], d.get('etag', None), d.get('modified', None), labels])
        feed_db_save(feeds)

        if ADD_ARCHIVE_NEW_FEED:
            valid_char = VALID_CHAR + ".-_"
            t = "".join(x for x in main_label if x in valid_char)
            path = os.path.join(ARCHIVE_PATH, t)
            with open(path, 'a') as f:
                for item in d.get('entries', None):
                    f.write("%s\n" % (item.get('title', item.get('link', item.get('id', ''))).encode('utf-8')))
    except:
        print "ERROR: adding url %s" % add_list[0]


def _list(array=False):  # is also used to load the db!
    feeds = []
    for index, l in enumerate(open(FEEDFILE_PATH, 'r').readlines(), 1):
        line = l.strip()
        if line != "":
            v = line.split('; ')
            if array:
                feeds.append(v)
            else:
                labels = v[3]
                for l in v[4:]:
                    labels += ", " + l
                print "%s.) %s [%s]" % (str(index), v[0].strip(), labels)
    if array:
        return feeds


def reset(nr):
    nr -= 1
    feeds = _list(True)
    if nr < 0:
        print "ID has to be equale to or higher than 1"
    elif nr > len(feeds):
        print "No such Feed"
    else:
        url = feeds[nr][3]
        if url.startswith('#'):
            url = url[2:]
        t = "".join(x for x in url if x in VALID_CHAR)
        path = os.path.join(ARCHIVE_PATH, t)
        if os.path.exists(path):
            os.remove(path)
            print 'The feed "%s" was sucessfull reseted!' % url
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
    nr -= 1
    feeds = _list(True)
    if nr < 0:
        print "ID has to be equale to or higher than 1"
    elif nr >= len(feeds):
        print "No such Feed"
    else:
        url = feeds[nr][3]
        if url.startswith('#'):
            url = url[2:]
        t = "".join(x for x in url if x in VALID_CHAR)
        path = os.path.join(ARCHIVE_PATH, t)
        if os.path.exists(path):
            os.remove(path)

        del feeds[nr]
        feed_db_save(feeds)
        print'The feed "%s" was sucessfull deleted!' % url


def email(addr):
    feeds, feedfileObject = load()
    if feeds and isstr(feeds[0]):
        feeds[0] = addr
    else:
        feeds = [addr] + feeds


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--configfile", help="Path to your config-file", metavar="<file>")
    parser.add_argument("--add", help="Add a Feedurl!", metavar="feedurl LABELS", nargs="+")
    parser.add_argument("--no-send", help="Only load the feed, without sending them", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--delete", help="Delete a Feedurl", metavar="<nr>", type=int)
    # parser.add_argument("--delete_read", help="Delete read mails from gmail", action="store_true")
    parser.add_argument("--reset", help="Reset a Feed-Archive-File", metavar="<nr>", type=int)
    parser.add_argument("--enable", help="Enable a Feed", metavar="<nr>", type=int)
    parser.add_argument("--disable", help="Disable a Feed", metavar="<nr>", type=int)
    parser.add_argument("--verbose", help="Get more information!", action="store_true")
    parser.add_argument("--version", action="version", version="%(prog)s {version}".format(version=__version__))
    parser.add_argument("integers", nargs="?", metavar="[num]", type=int)
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
        VERBOSE = args.verbose
        if args.list:
            _list()
        # elif args.delete_read:
            # delete_read()
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
