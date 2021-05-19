#!/usr/bin/env python3

from lru import LRU
import gzip
import sys
import warcio
import tempfile
import base64
import subprocess
from sentence_splitter import SentenceSplitter, SentenceSplitterException
import glob
from warcio.archiveiterator import ArchiveIterator
from warcio.warcwriter import WARCWriter

l = LRU(100000) # A cache with size of 100K documents in memory

if len(sys.argv) < 4 or "--help" in sys.argv or "-h" in sys.argv:
    print("Usage: deferred-annotation-reconstructor BITEXTOR-OUTPUT-FILE LANG-CODE-SL LANG-CODE-TL [WARCFILE]")
    print("Reconstructs sentences from deferred crawling standoff annotations from Bitextor")
    print()
    print("All arguments are positional.")
    print()
    print("Report bugs to: https://github.com/bitextor/bitextor/issues")
    print("Bitextor home page: <https://github.com/bitextor/bitextor>")
    exit()

with gzip.open(sys.argv[1], 'rt') as bitextor_output:
    for line in bitextor_output:
        # Parse bitextor ".sent.gz" line with deferred crawling annotations
        parts_line = line.rstrip('\n').split('\t')
        deferredhash1 = parts_line[5]
        deferredhash2 = parts_line[6]
        url1 = parts_line[0]
        url2 = parts_line[1]
        # Use print to output the same format from the input but with reconstructed sentences once we get them
        print(url1 + "\t" + url2, end='')
        
        # For source and target language
        for url, deferredhash, langcode in [(url1,deferredhash1,sys.argv[2]), (url2,deferredhash2,sys.argv[3])]:
            if url not in l: # If we don't crawled or retrieved the document where this sentence is located
                l[url]=dict() # Init the cache if the url didn't exist with a Python dictionary, which will store the deferred annotation and the actual sentence
                fp = tempfile.NamedTemporaryFile(suffix=".warc.gz") # File to store the WARC records/documents that match their URL
                if len(sys.argv) == 5: # if an already crawled WARC is given by argument, let's look for the content of the url from the line we are actually iterating on
                    writer = WARCWriter(fp, gzip=True)
                    for record in ArchiveIterator(open(sys.argv[4],'rb')):
                        if url == record.rec_headers.get_header('WARC-Target-URI'):
                            writer.write_record(record)
                else: # download the url with wget
                    with tempfile.TemporaryDirectory() as tempcrawling:
                        subprocess.run(["wget", url, "-P", tempcrawling, "-o", "/dev/null", "--warc-file", ".".join(fp.name.split('.')[:-2])])

                with tempfile.TemporaryDirectory() as tempprocess:
                    # Process the downloaded document the same way Bitextor does in Paracrawl (warc2text + Moses sentence splitter Python port)
                    subprocess.run(["warc2text/bin/warc2text", "-o", tempprocess, fp.name], stderr=subprocess.DEVNULL)
                    fp.close()
                    splitter = None
                    try:
                        splitter = SentenceSplitter(language=langcode)
                    except SentenceSplitterException as e:
                        sys.stderr.write(str(e)+"\n")
                        splitter = SentenceSplitter(language='en')
                    for filename in glob.glob(tempprocess + "/*/text.gz"):
                        with gzip.open(filename, 'r') as f:
                            segments = splitter.split(base64.b64decode(f.read()).decode('utf8'))
                            for segment in segments:
                                segment = segment.rstrip('\n')
                                # Then calculate the MurmurHash for each sentence from the downloaded document like Bitextor does, and then store it in the cache
                                l[url][subprocess.run(["preprocess/bin/mmhsum"], stdout=subprocess.PIPE, input=segment, encoding='utf8').stdout.rstrip('\n')]=segment
    
            # Print the reconstructed sentences
            print("\t", end='')
            list_sentences = []
            for partdeferredhash in deferredhash.split('#')[0].split('+'):
                try:
                    list_sentences.append(l[url][partdeferredhash])
                except KeyError: # if the sentence hasn't been found
                    list_sentences.append('')
            print(" ".join(list_sentences), end='')
        print("\t" + "\t".join(parts_line[4:]))

