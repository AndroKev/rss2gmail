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

import os, sys, re, time
import argparse
from datetime import datetime, timedelta
import socket, urllib2, urlparse, imaplib
urllib2.install_opener(urllib2.build_opener())
import traceback, types
from types import *
import csv

from email.MIMEText import MIMEText
from email.Header import Header
from email.Utils import parseaddr, formataddr

import feedparser
import html2text as h2t

feedparser.USER_AGENT = "rss2gmail/"+__version__+ " +https://github.com/AndroKev/rss2gmail"
VALID_CHAR = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
DEFAULT_IMAP_FOLDER = "INBOX"
warn = sys.stderr

# Read options from config file if present.
sys.path.insert(0,".")
try:
    from config import *
except:
    print >>warn, "No config-file found!"
    print >>warn, "Please rename config.py.example to config.py, edit it und try it again!"
    sys.exit(1)

h2t.UNICODE_SNOB = UNICODE_SNOB
h2t.LINKS_EACH_PARAGRAPH = LINKS_EACH_PARAGRAPH
h2t.BODY_WIDTH = BODY_WIDTH
html2text = h2t.html2text

### Mail Functions ###

def send(sender, recipient, subject, body, contenttype, when, extraheaders=None, mailserver=None, folder=None):
    """Send an email.

    All arguments should be Unicode strings (plain ASCII works as well).

    Only the real name part of sender and recipient addresses may contain
    non-ASCII characters.

    The email will be properly MIME encoded and delivered though SMTP to
    localhost port 25.  This is easy to change if you want something different.

    The charset of the email will be the first one out of the list
    that can represent all the characters occurring in the email.
    """

    # Header class is smart enough to try US-ASCII, then the charset we
    # provide, then fall back to UTF-8.
    header_charset = 'ISO-8859-1'

    # We must choose the body charset manually
    for body_charset in CHARSET_LIST:
        try:
            body.encode(body_charset)
        except (UnicodeError, LookupError):
            pass
        else:
            break

    # Split real name (which is optional) and email address parts
    sender_name, sender_addr = parseaddr(sender)
    recipient_name, recipient_addr = parseaddr(recipient)

    # We must always pass Unicode strings to Header, otherwise it will
    # use RFC 2047 encoding even on plain ASCII strings.
    sender_name = str(Header(unicode(sender_name), header_charset))
    recipient_name = str(Header(unicode(recipient_name), header_charset))

    # Make sure email addresses do not contain non-ASCII characters
    sender_addr = sender_addr.encode('ascii')
    recipient_addr = recipient_addr.encode('ascii')

    # Create the message ('plain' stands for Content-Type: text/plain)
    msg = MIMEText(body.encode(body_charset), contenttype, body_charset)
    msg['To'] = formataddr((recipient_name, recipient_addr))
    msg['Subject'] = Header(unicode(subject), header_charset)
    for hdr in extraheaders.keys():
        try:
            msg[hdr] = Header(unicode(extraheaders[hdr], header_charset))
        except:
            msg[hdr] = Header(extraheaders[hdr])

    fromhdr = formataddr((sender_name, sender_addr))
    msg['From'] = fromhdr

    msg_as_string = msg.as_string()

    if not mailserver:
        try:
            mailserver = imaplib.IMAP4_SSL("imap.gmail.com", 994)
            # speed up interactions on TCP connections using small packets
            mailserver.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            mailserver.login(GMAIL_PASS, GMAIL_PASS)
        except KeyboardInterrupt:
            raise
        except Exception, e:
            print >>warn, ""
            print >>warn, ('Fatal error: could not connect to mail server "%s"' % IMAP_SERVER)
            print >>warn, ('Check your config.py file to confirm that IMAP_SERVER and other mail server settings are configured properly')
            if hasattr(e, 'reason'):
                print >>warn, "Reason:", e.reason
            sys.exit(1)
    if not folder:
        folder = DEFAULT_IMAP_FOLDER
    #mailserver.debug = 4
    if mailserver.select(folder)[0] == 'NO':
        print >>warn, ("%s does not exist, creating" % folder)
        mailserver.create(folder)
        mailserver.subscribe(folder)
    mailserver.append(folder,'',imaplib.Time2Internaldate(when), msg_as_string)
    return mailserver

### Utility Functions ###

class InputError(Exception): pass

def isstr(f): return isinstance(f, type('')) or isinstance(f, type(u''))
def ishtml(t): return type(t) is type(())
def contains(a,b): return a.find(b) != -1
def unu(s): # I / freakin' hate / that unicode
    if type(s) is types.UnicodeType: return s.encode('utf-8')
    else: return s

### Parsing Utilities ###

def getContent(entry, HTMLOK=0):
    """Select the best content from an entry, deHTMLizing if necessary.
    If raw HTML is best, an ('HTML', best) tuple is returned. """

    # How this works:
    #  * We have a bunch of potential contents.
    #  * We go thru looking for our first choice.
    #    (HTML or text, depending on HTMLOK)
    #  * If that doesn't work, we go thru looking for our second choice.
    #  * If that still doesn't work, we just take the first one.
    #
    # Possible future improvement:
    #  * Instead of just taking the first one
    #    pick the one in the "best" language.
    #  * HACK: hardcoded HTMLOK, should take a tuple of media types

    conts = entry.get('content', [])

    if entry.get('summary_detail', {}):
        conts += [entry.summary_detail]

    if conts:
        if HTMLOK:
            for c in conts:
                if contains(c.type, 'html'): return ('HTML', c.value)

        if not HTMLOK: # Only need to convert to text if HTML isn't OK
            for c in conts:
                if contains(c.type, 'html'):
                    return html2text(c.value)

        for c in conts:
            if c.type == 'text/plain': return c.value

        return conts[0].value

    return ""

def getName(r, entry):
    """Get the best name."""

    if NO_FRIENDLY_NAME: return ''

    feed = r.feed
    if hasattr(r, "url") and r.url in OVERRIDE_FROM.keys():
        return OVERRIDE_FROM[r.url]

    name = feed.get('title', '')

    if 'name' in entry.get('author_detail', []): # normally {} but py2.1
        if entry.author_detail.name:
            if name: name += ": "
            det=entry.author_detail.name
            try:
                name +=  entry.author_detail.name
            except UnicodeDecodeError:
                name +=  unicode(entry.author_detail.name, 'utf-8')

    elif 'name' in feed.get('author_detail', []):
        if feed.author_detail.name:
            if name: name += ", "
            name += feed.author_detail.name

    return name

def getMungedFrom(r):
    """Generate a better From."""

    feed = r.feed
    if hasattr(r, "url") and r.url in OVERRIDE_FROM.keys():
        return OVERRIDE_FROM[r.url]

    name = feed.get('title', 'unknown').lower()
    pattern = re.compile('[\W_]+',re.UNICODE)
    re.sub(pattern, '', name)
    name = "%s <%s@%s>" % (feed.get('title','Unnamed Feed'), name.replace(' ','_'), urlparse.urlparse(r.url).netloc)
    return name

def validateEmail(email, planb):
    """Do a basic quality check on email address, but return planb if email doesn't appear to be well-formed"""
    email_parts = email.split('@')
    if len(email_parts) != 2:
        return planb
    return email

def getEmail(r, entry):
    """Get the best email_address. If the best guess isn't well-formed (something@somthing.com), use DEFAULT_EMAIL_FROM instead"""

    feed = r.feed

    if FORCE_FROM: return DEFAULT_EMAIL_FROM

    if hasattr(r, "url") and r.url in OVERRIDE_EMAIL.keys():
        return validateEmail(OVERRIDE_EMAIL[r.url], DEFAULT_EMAIL_FROM)

    if 'email' in entry.get('author_detail', []):
        return validateEmail(entry.author_detail.email, DEFAULT_EMAIL_FROM)

    if 'email' in feed.get('author_detail', []):
        return validateEmail(feed.author_detail.email, DEFAULT_EMAIL_FROM)

    if USE_PUBLISHER_EMAIL:
        if 'email' in feed.get('publisher_detail', []):
            return validateEmail(feed.publisher_detail.email, DEFAULT_EMAIL_FROM)

        if feed.get("errorreportsto", ''):
            return validateEmail(feed.errorreportsto, DEFAULT_EMAIL_FROM)

    if hasattr(r, "url") and r.url in DEFAULT_EMAIL.keys():
        return DEFAULT_EMAIL[r.url]
    return DEFAULT_EMAIL_FROM

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
                if VERBOSE: print >>warn, 'I: Processing [%d] "%s"' % (feednum, f[0])
                r = {}
                r = feedparser.parse(f[0], f[2], f[3])
                if r.get('status', None) == 304:
                    print "skipped: %s" % f[0]
                    continue

                t = "".join(x for x in f[0] if x in VALID_CHAR)
                path = os.path.join(ARCHIVE_PATH, t)
                seen = open(path, 'r').readlines()

                r.entries.reverse()
                for entry in r.entries:
                    uid = entry.get('id', entry.get('link', entry.get('title', None)))
                    if uid+'\n' in seen:continue
                    # new entry:
                    title = entry.get('title', None).strip()
                    puplished = entry.get('published', "datum+zeit")
                    author = entry.get('author', f[4])
                    article = entry.get('content', None)
                    article_value = article[0].get('value', None)
                    print title
                    print puplished
                    print author
                    print article
                    print article_value

                    with open(path, 'a') as f:
                        f.write("%s\n" % uid)
                    continue

                    if 'title_detail' in entry and entry.title_detail:
                        title = entry.title_detail.value
                        if contains(entry.title_detail.type, 'html'):
                            title = html2text(title)
                    else:
                        title = getContent(entry)[:70]

                    title = title.replace("\n", " ").strip()

                    when = time.gmtime()

                    if DATE_HEADER:
                        for datetype in DATE_HEADER_ORDER:
                            kind = datetype+"_parsed"
                            if kind in entry and entry[kind]: when = entry[kind]

                    link = entry.get('link', "")

                    from_addr = getEmail(r, entry)

                    name = h2t.unescape(getName(r, entry))
                    fromhdr = formataddr((name, from_addr,))
                    tohdr = (f.to or default_to)
                    subjecthdr = title
                    datehdr = time.strftime("%a, %d %b %Y %H:%M:%S -0000", when)
                    useragenthdr = "rss2email"

                    # Add post tags, if available
                    tagline = ""
                    if 'tags' in entry:
                        tags = entry.get('tags')
                        taglist = []
                        if tags:
                            for tag in tags:
                                taglist.append(tag['term'])
                        if taglist:
                            tagline = ",".join(taglist)

                    extraheaders = {'Date': datehdr, 'User-Agent': useragenthdr, 'X-RSS-Feed': f[0], 'Message-ID': '<%s>' % hashlib.sha1(id.encode('utf-8')).hexdigest(), 'X-RSS-ID': id, 'X-RSS-URL': link, 'X-RSS-TAGS' : tagline, 'X-MUNGED-FROM': getMungedFrom(r), 'References': ''}
                    if BONUS_HEADER != '':
                        for hdr in BONUS_HEADER.strip().splitlines():
                            pos = hdr.strip().find(':')
                            if pos > 0:
                                extraheaders[hdr[:pos]] = hdr[pos+1:].strip()
                            else:
                                print >>warn, "W: malformed BONUS HEADER", BONUS_HEADER

                    entrycontent = getContent(entry, HTMLOK=HTML_MAIL)
                    contenttype = 'plain'
                    content = ''
                    if THREAD_ON_TAGS and len(tagline):
                        extraheaders['References'] += ''.join([' <%s>' % hashlib.sha1(t.strip().encode('utf-8')).hexdigest() for t in tagline.split(',')])
                    if USE_CSS_STYLING and HTML_MAIL:
                        contenttype = 'html'
                        content = "<html>\n"
                        content += '<head><meta http-equiv="Content-Type" content="text/html"><style>' + STYLE_SHEET + '</style></head>\n'
                        content += '<body style="word-wrap: break-word; -webkit-nbsp-mode: space; -webkit-line-break: after-white-space;">\n'
                        content += '<div id="entry">\n'
                        content += '<h1 class="header"'
                        content += '><a href="'+link+'">'+subjecthdr+'</a></h1>\n'
                        if ishtml(entrycontent):
                            body = entrycontent[1].strip()
                        else:
                            body = entrycontent.strip()
                        if INLINE_IMAGES_DATA_URI:
                            parser = Parser(tag='img', attr='src')
                            parser.feed(body)
                            for src in parser.attrs:
                                try:
                                    img = feedparser._open_resource(src, None, None, feedparser.USER_AGENT, link, [], {})
                                    data = img.read()
                                    if hasattr(img, 'headers'):
                                        headers = dict((k.lower(), v) for k, v in dict(img.headers).items())
                                        ctype = headers.get('content-type', None)
                                        if ctype and INLINE_IMAGES_DATA_URI:
                                            body = body.replace(src,'data:%s;base64,%s' % (ctype, base64.b64encode(data)))
                                except:
                                    print >>warn, "Could not load image: %s" % src
                                    pass
                        if body != '':
                            content += '<div id="body">\n' + body + '</div>\n'
                        content += '\n<p class="footer">URL: <a href="'+link+'">'+link+'</a>'
                        if hasattr(entry,'enclosures'):
                            for enclosure in entry.enclosures:
                                if (hasattr(enclosure, 'url') and enclosure.url != ""):
                                    content += ('<br/>Enclosure: <a href="'+enclosure.url+'">'+enclosure.url+"</a>\n")
                                if (hasattr(enclosure, 'src') and enclosure.src != ""):
                                    content += ('<br/>Enclosure: <a href="'+enclosure.src+'">'+enclosure.src+'</a><br/><img src="'+enclosure.src+'"\n')
                        if 'links' in entry:
                            for extralink in entry.links:
                                if ('rel' in extralink) and extralink['rel'] == u'via':
                                    extraurl = extralink['href']
                                    extraurl = extraurl.replace('http://www.google.com/reader/public/atom/', 'http://www.google.com/reader/view/')
                                    viatitle = extraurl
                                    if ('title' in extralink):
                                        viatitle = extralink['title']
                                    content += '<br/>Via: <a href="'+extraurl+'">'+viatitle+'</a>\n'
                        content += '</p></div>\n'
                        content += "\n\n</body></html>"
                    else:
                        if ishtml(entrycontent):
                            contenttype = 'html'
                            content = "<html>\n"
                            content = ("<html><body>\n\n" +
                                       '<h1><a href="'+link+'">'+subjecthdr+'</a></h1>\n\n' +
                                       entrycontent[1].strip() + # drop type tag (HACK: bad abstraction)
                                       '<p>URL: <a href="'+link+'">'+link+'</a></p>' )

                            if hasattr(entry,'enclosures'):
                                for enclosure in entry.enclosures:
                                    if enclosure.url != "":
                                        content += ('Enclosure: <a href="'+enclosure.url+'">'+enclosure.url+"</a><br/>\n")
                            if 'links' in entry:
                                for extralink in entry.links:
                                    if ('rel' in extralink) and extralink['rel'] == u'via':
                                        content += 'Via: <a href="'+extralink['href']+'">'+extralink['title']+'</a><br/>\n'

                            content += ("\n</body></html>")
                        else:
                            content = entrycontent.strip() + "\n\nURL: "+link
                            if hasattr(entry,'enclosures'):
                                for enclosure in entry.enclosures:
                                    if enclosure.url != "":
                                        content += ('\nEnclosure: ' + enclosure.url + "\n")
                            if 'links' in entry:
                                for extralink in entry.links:
                                    if ('rel' in extralink) and extralink['rel'] == u'via':
                                        content += '<a href="'+extralink['href']+'">Via: '+extralink['title']+'</a>\n'

                    mailserver = send(fromhdr, tohdr, subjecthdr, content, contenttype, when, extraheaders, mailserver, f.folder)

                    f.seen[frameid] = id

                continue
                f.etag, f.modified = r.get('etag', None), r.get('modified', None)
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                print >>warn, "=== rss2email encountered a problem with this feed ==="
                print >>warn, "=== See the rss2email FAQ at http://www.allthingsrss.com/rss2email/ for assistance ==="
                print >>warn, "=== If this occurs repeatedly, send this to lindsey@allthingsrss.com ==="
                print >>warn, "E: could not parse", f[0]
                traceback.print_exc(file=warn)
                print >>warn, "rss2email", __version__
                print >>warn, "feedparser", feedparser.__version__
                print >>warn, "html2text", h2t.__version__
                print >>warn, "Python", sys.version
                print >>warn, "=== END HERE ==="
                continue

    finally:
        if mailserver:
            if IMAP_MARK_AS_READ:
                for folder in IMAP_MARK_AS_READ:
                    mailserver.select(folder)
                    res, data = mailserver.search(None, '(UNSEEN UNFLAGGED)')
                    if res == 'OK':
                        items = data[0].split()
                        for i in items:
                            res, data = mailserver.fetch(i, "(UID)")
                            if data[0]:
                                u = uid(data[0])
                                res, data = mailserver.uid('STORE', u, '+FLAGS', '(\Seen)')
            if IMAP_MOVE_READ_TO:
                typ, data = mailserver.list(pattern='*')
                # Parse folder listing as a CSV dialect (automatically removes quotes)
                reader = csv.reader(StringIO.StringIO('\n'.join(data)),dialect='mailboxlist')
                # Iterate over each folder
                for row in reader:
                    folder = row[-1:][0]
                    if folder == IMAP_MOVE_READ_TO or '\Noselect' in row[0]:
                        continue
                    mailserver.select(folder)
                    yesterday = (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y")
                    res, data = mailserver.search(None, '(SEEN BEFORE %s UNFLAGGED)' % yesterday)
                    if res == 'OK':
                        items = data[0].split()
                        for i in items:
                            res, data = mailserver.fetch(i, "(UID)")
                            if data[0]:
                                u = uid(data[0])
                                res, data = mailserver.uid('COPY', u, IMAP_MOVE_READ_TO)
                                if res == 'OK':
                                    res, data = mailserver.uid('STORE', u, '+FLAGS', '(\Deleted)')
                                    mailserver.expunge()
            try:
                mailserver.quit()
            except:
                mailserver.logout()

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


### HTML Parser for grabbing links and images ###

from HTMLParser import HTMLParser
class Parser(HTMLParser):
    def __init__(self, tag = 'a', attr = 'href'):
        HTMLParser.__init__(self)
        self.tag = tag
        self.attr = attr
        self.attrs = []
    def handle_starttag(self, tag, attrs):
        if tag == self.tag:
            attrs = dict(attrs)
            if self.attr in attrs:
                self.attrs.append(attrs[self.attr])


### CSV dialect for parsing IMAP responses
class mailboxlist(csv.excel):
    delimiter = ' '


csv.register_dialect('mailboxlist',mailboxlist)


def uid(data):
    m = re.match('\d+ \(UID (?P<uid>\d+)\)', data)
    return m.group('uid')

def email(addr):
    feeds, feedfileObject = load()
    if feeds and isstr(feeds[0]): feeds[0] = addr
    else: feeds = [addr] + feeds

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    #parser.add_argument("-c", "--configdir", help="Run with <dir> as config directory", metavar="<dir>")
    # parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--no-send", help="Only load the feed, without sending them", action="store_true")
    parser.add_argument("--add", help="Add a Feedurl to the FEEDFILE_PATH", metavar="feedurl (LABELS)", nargs="+")
    parser.add_argument("-l", "--list", action="store_true")
    parser.add_argument("-d", "--delete", help="Delete an Feedurl", metavar="<nr>", type=int)
    parser.add_argument("--reset", help="Reset an Feed-Archive-File", metavar="<nr>", type=int)
    parser.add_argument("--enable", help="Enable a Feed", metavar="<nr>", type=int)
    parser.add_argument("--disable", help="Disable a Feed", metavar="<nr>", type=int)
    parser.add_argument("-V", "--version", action='version', version='%(prog)s {version}'.format(version=__version__))
    args = parser.parse_args()

    if not os.path.exists(FEEDFILE_PATH):
        open(FEEDFILE_PATH,"w").close()
    if not os.path.exists(ARCHIVE_PATH):
        os.makedirs(ARCHIVE_PATH)

    if GMAIL_PASS == "" or GMAIL_USER == "":
        print """It seams that you run the tool the first time.
Please edit the config file to your need and start the tool again!"""
    else:
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
