#!/usr/bin/env python3

import html
from warcio.archiveiterator import ArchiveIterator
from warcio.warcwriter import WARCWriter
import base64
import sys
import argparse
import cchardet
import hashlib
import magic
import re
import ftfy
from lxml.html.clean import Cleaner
from bs4 import BeautifulSoup
import jpype
import os
import imp
import alcazar.bodytext
import logging
import lzma
import subprocess
import gzip
import zipfile
import io
from selectolax.parser import HTMLParser
import mmh3
from io import BytesIO

if not jpype.isJVMStarted():
    jars = []
    for top, dirs, files in os.walk(imp.find_module('pdfextract')[1] + '/data'):
        for nm in files:
            if nm[-4:] == ".jar":
                jars.append(os.path.join(top, nm))
    for top, dirs, files in os.walk(imp.find_module('boilerpipe')[1] + '/data'):
        for nm in files:
            if nm[-4:] == ".jar":
                jars.append(os.path.join(top, nm))
    jpype.addClassPath(os.pathsep.join(jars))
    jpype.startJVM(jpype.getDefaultJVMPath(), convertStrings=False)
from boilerpipe.extract import Extractor as ExtrB
from pdfextract.extract import Extractor as ExtrP


def convert_encoding(data):
    encoding = cchardet.detect(data)['encoding']
    if encoding is None:
        encoding = "utf-8"
    if len(data) > 0:
        # We convert, even if the text is detected to be UTF8 so, if it is an error and conversion fails, the error
        # is catched here
        for enc in [encoding, 'utf-8', 'iso-8859-1', 'windows‑1252']:
            try:
                return enc, data.decode(enc)
            except:
                pass
    return None, ''


def pdf2html(data):
    pconverter = subprocess.Popen(["pdftohtml", "-i", "-stdout", "-", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    converter_stdout, error = pconverter.communicate(input=data)
    return [converter_stdout.replace(b"&#160;", b" ")]


def pdfextract_shell(data):
    pconverter = subprocess.Popen(["sh", "-c", "datafile=`mktemp`; cat - > $datafile.pdf; dataoutputfile=`mktemp`; java -jar pdf-extract/runnable-jar/PDFExtract.jar -I $datafile.pdf -O $dataoutputfile > /dev/null ; cat $dataoutputfile ; rm $datafile $datafile.pdf $dataoutputfile"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    converter_stdout, error = pconverter.communicate(input=data)
    return [converter_stdout]


def pdfextract(data, extractor):
    extractor.setData(data)
    try:
        return [bytes(extractor.getHTML(), 'utf8')]
    except:
        return [b""]


def openoffice2html(data):
    datastream = io.BytesIO(data)
    try:
        openoffice_file = zipfile.ZipFile(datastream)
    except zipfile.BadZipFile:
        return []
    return [openoffice_file.read('content.xml')]


def office2html(data):
    datastream = io.BytesIO(data)
    try:
        office_file = zipfile.ZipFile(datastream)
    except zipfile.BadZipFile:
        return []
    # word/document.xml, ppt/slides/slide*.xml, xl/sharedStrings.xml
    xmls = []
    for xml in office_file.namelist():
        if "word/document.xml" == xml or "ppt/slides/slide" == xml[0:16] or "xl/sharedStrings.xml" == xml:
            xmls.append(office_file.read(xml))
    return xmls


def epub2html(data):
    datastream = io.BytesIO(data)
    try:
        epub_file = zipfile.ZipFile(datastream)
    except zipfile.BadZipFile:
        return []
    # EPUB/*html
    xmls = []
    for xml in epub_file.namelist():
        if "ml" == xml[-2:]:
            xmls.append(epub_file.read(xml))
    return xmls


oparser = argparse.ArgumentParser(
    description="Script that takes every record in a WARC file and runs basic preprocessing, which includes: HTML"
                "normalization, deduplication. The result is a WARC file.")
oparser.add_argument("--verbose", action="store_true", default=False,
                     help="Produce additional information about preprocessing through stderr.")
oparser.add_argument('--output', dest='output', help='Output WARC file', required=True)
oparser.add_argument('--input', dest='input', help='Input WARC file', default=sys.stdin)
oparser.add_argument('--pdfextract', action="store_true", help='Use pdf-extract engine or pdftohtml for PDFs',
                     default=False)
options = oparser.parse_args()

logging.basicConfig(format='%(asctime)s %(levelname)-8s %(message)s', level=logging.INFO if options.verbose else logging.ERROR, datefmt='%Y-%m-%d %H:%M:%S')
f = None
fo = None
if options.input[-3:] == ".xz":
    f = ArchiveIterator(lzma.open(options.input, 'r'))
elif options.input[-3:] == ".gz":
    f = ArchiveIterator(gzip.open(options.input, 'r'))
elif options.input == sys.stdin:
    f = ArchiveIterator(options.input.buffer)
else:
    f = ArchiveIterator(open(options.input, 'rb'))

fo = WARCWriter(open(options.output,'wb'), gzip=True)

if options.pdfextract:
    extractor = ExtrP()

cleaner = Cleaner(style=True, links=True, add_nofollow=True, page_structure=False, safe_attrs_only=False)


for record in f:
    # Initial checks
    if record.rec_type != 'response':
        continue
    if record.rec_headers.get_header('WARC-Target-URI')[0] == '<' and record.rec_headers.get_header('WARC-Target-URI')[-1] == '>':
        url = record.rec_headers.get_header('WARC-Target-URI')[1:-1]
    else:
        url = record.rec_headers.get_header('WARC-Target-URI')
    if url == "unknown":
        logging.info("Skipping page with unknown URL")
        continue
    if "text/dns" in record.rec_headers.get_header('Content-Type'):
        continue
    pageSize = int(record.rec_headers.get_header('Content-Length'))
    if pageSize > 5242880:
        logging.info("Skipping page, over limit. " + str(pageSize) + " " + url)
        continue
    if record.http_headers is not None and record.http_headers.get_header('Content-Type') is not None:
        if "image/" in record.http_headers.get_header('Content-Type') or "audio/" in record.http_headers.get_header(
                'Content-Type') or "video/" in record.http_headers.get_header(
                'Content-Type') or "text/x-component" in record.http_headers.get_header(
                'Content-Type') or "text/x-js" in record.http_headers.get_header(
                'Content-Type') or "text/javascript" in record.http_headers.get_header(
                'Content-Type') or "application/x-javascript" in record.http_headers.get_header(
                'Content-Type') or "text/css" in record.http_headers.get_header(
                'Content-Type') or "application/javascript" in record.http_headers.get_header(
                'Content-Type') or "application/x-shockwave-flash" in record.http_headers.get_header(
                'Content-Type') or "application/octet-stream" in record.http_headers.get_header(
                'Content-Type') or "application/x-font-ttf" in record.http_headers.get_header('Content-Type'):
            continue
    url = url.lower()
    url = url.replace('\t',' ')
    if url[-4:] == ".gif" or url[-4:] == ".jpg" or url[-5:] == ".jpeg" or url[-4:] == ".png" or url[-4:] == ".css" or url[-3:] == ".js" or url[-4:] == ".mp3" or url[-4:] == ".mp4" or url[-4:] == ".ogg" or url[-5:] == ".midi" or url[-4:] == ".swf":
        continue
    # print("url", num, url, pageSize)

    # Ignore robots.txt when processing records
    if url[-11:] == "/robots.txt":
        continue
    payload = record.content_stream().read()
    payloads = []

    # Extract payloads (XML) from non-HTML document formats
    if url[-4:] == ".pdf" or ((record.http_headers is not None and record.http_headers.get_header('Content-Type') is not None) and "application/pdf" in record.http_headers.get_header('Content-Type')):
        if options.pdfextract:
            payloads = pdfextract(payload, extractor)
            # payloads = pdfextract_shell(payload)
        else:
            payloads = pdf2html(payload)
    elif url[-4:] == ".odt" or url[-4:] == ".ods" or url[-4:] == ".odp":
        payloads = openoffice2html(payload)
    elif url[-5:] == ".docx" or url[-5:] == ".pptx" or url[-5:] == ".xlsx":
        payloads = office2html(payload)
    elif url[-5:] == ".epub":
        payloads = epub2html(payload)
    else:
        payloads = [payload]

    date = record.rec_headers.get_header('WARC-Date')
    recordId = record.rec_headers.get_header('WARC-Record-ID')
    for payload in payloads:
        # We convert into UTF8 first of all
        orig_encoding, text = convert_encoding(payload)
        logging.info("Processing document: " + url)
        if orig_encoding is None:
            logging.info("Encoding of document " + url + " could not be identified")

        if len(text) > 0:
            # HTML is then normalized
            logging.info(url + ": cleaning html")
            tree = ""
            try:
                cleanhtml = cleaner.clean_html(re.sub('encoding *= *"[^"]+"', '', text, flags=re.IGNORECASE))
                tree = ftfy.fix_text(cleanhtml, fix_entities=False, fix_character_width=False)
            except Exception as ex:
                sys.stderr.write(str(ex) + "\n")
                continue
            cleantree = tree.replace("&#160;", " ")
            cleantree = cleantree.replace("\t", " ")
            fo.write_record(fo.create_warc_record(uri=url, record_type='response', payload=BytesIO(cleantree.encode('utf8')), warc_headers=record.rec_headers, http_headers=record.http_headers))



