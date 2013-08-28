import h2o, h2o_cmd, re, os

# hdfs/maprfs/s3/s3n paths should be absolute from the bucket (top level)
# so only walk around for local
def find_folder_path_and_pattern(bucket, pathWithRegex):
    # strip the common mistake of leading "/" in path, if bucket is specified too
    if bucket is not None and re.match("/", pathWithRegex):
        h2o.verboseprint("You said bucket:", bucket, "so stripping incorrect leading '/' from", pathWithRegex)
        pathWithRegex = pathWithRegex.lstrip('/')

    if bucket is None:  # good for absolute path name
        bucketPath = ""

    elif bucket == ".":
        bucketPath = os.getcwd()

    # does it work to use bucket "." to get current directory
    elif os.environ.get('H2O_BUCKETS_ROOT'):
        h2oBucketsRoot = os.environ.get('H2O_BUCKETS_ROOT')
        print "Using H2O_BUCKETS_ROOT environment variable:", h2oBucketsRoot

        rootPath = os.path.abspath(h2oBucketsRoot)
        if not (os.path.exists(rootPath)):
            raise Exception("H2O_BUCKETS_ROOT in env but %s doesn't exist." % rootPath)

        bucketPath = os.path.join(rootPath, bucket)
        if not (os.path.exists(bucketPath)):
            raise Exception("H2O_BUCKETS_ROOT and path used to form %s which doesn't exist." % bucketPath)

    else:
        # if we run remotely, we're assuming the import folder path on the remote machine
        # matches what we find on our local machine. But maybe the local user doesn't exist remotely 
        # so using his path won't work. 
        # Resolve by looking for special state in the config. If user = 0xdiag, just force the bucket location
        # This is a lot like knowing about fixed paths with s3 and hdfs
        # Otherwise the remote path needs to match the local discovered path.

        # want to check the username being used remotely first. should exist here too if going to use
        possibleUsers = ["~"]
        print "username:", h2o.nodes[0].username
        if h2o.nodes[0].username:
            possibleUsers.insert(0, "~" + h2o.nodes[0].username)

        for u in possibleUsers:
            rootPath= os.path.expanduser(u)
            bucketPath = os.path.join(rootPath, bucket)
            print "Checking bucketPath:", bucketPath, 'assuming home is', rootPath
            if os.path.exists(bucketPath):
                print "Did find", bucket, "at", rootPath
                break

        else:
            rootPath = os.getcwd()
            h2o.verboseprint("find_bucket looking upwards from", rootPath, "for", bucket)
            # don't spin forever 
            levels = 0
            while not (os.path.exists(os.path.join(rootPath, bucket))):
                h2o.verboseprint("Didn't find", bucket, "at", rootPath)
                rootPath = os.path.split(rootPath)[0]
                levels += 1
                if (levels==6):
                    raise Exception("unable to find bucket: %s" % bucket)

            print "Did find", bucket, "at", rootPath
            bucketPath = os.path.join(rootPath, bucket)

    # if there's no path, just return the bucketPath
    # but what about cases with a header in the folder too? (not putfile)
    if pathWithRegex is None:
        return (bucketPath, None)

    # if there is a "/" in the path, that means it's not just a pattern
    # split it
    # otherwise it is a pattern. use it to search for files in python first? 
    # FIX! do that later
    elif "/" in pathWithRegex:
        (head, tail) = os.path.split(pathWithRegex)
        folderPath = os.path.abspath(os.path.join(bucketPath, head))
        if not os.path.exists(folderPath):
            raise Exception("%s doesn't exist. %s under %s may be wrong?" % (folderPath, head, bucketPath))
    else:
        folderPath = bucketPath
        tail = pathWithRegex
        
    h2o.verboseprint("folderPath:", folderPath, "tail:", tail)
    return (folderPath, tail)


# passes additional params thru kwargs for parse
# use_header_file=
# header=
# exclude=
# src_key= only used if for put file key name (optional)
# path should point to a file or regex of files. (maybe folder works? but unnecessary
def import_only(node=None, schema='local', bucket=None, path=None,
    timeoutSecs=30, retryDelaySecs=0.5, initialDelaySecs=0.5, pollTimeoutSecs=180, noise=None,
    noPoll=False, doSummary=True, src_key='python_src_key', **kwargs):

    # no bucket is sometimes legal (fixed path)
    if not node: node = h2o.nodes[0]

    if "/" in path:
        (head, pattern) = os.path.split(path)
    else:
        (head, pattern)  = ("", path)

    h2o.verboseprint("head:", head)
    h2o.verboseprint("pattern:", pattern)

    # to train users / okay here
    if re.search(r"[\*<>{}[\]~`]", head):
       raise Exception("h2o folder path %s can't be regex. path= was %s" % (head, path))

    if schema=='put':
        # to train users
        if re.search(r"[/\*<>{}[\]~`]", pattern):
           raise Exception("h2o putfile basename %s can't be regex. path= was %s" % (pattern, path))

        if not path: 
            raise Exception("path= didn't say what file to put")

        (folderPath, filename) = find_folder_path_and_pattern(bucket, path)
        h2o.verboseprint("folderPath:", folderPath, "filename:", filename)
        filePath = os.path.join(folderPath, filename)
        h2o.verboseprint('filePath:', filePath)
        key = node.put_file(filePath, key=src_key, timeoutSecs=timeoutSecs)
        return (None, key)

    if schema=='local':
        (folderPath, pattern) = find_folder_path_and_pattern(bucket, path)
        folderURI = 'nfs:/' + folderPath
        importResult = node.import_files(folderPath, timeoutSecs=timeoutSecs)

    else:
        if bucket is not None and re.match("/", head):
            h2o.verboseprint("You said bucket:", bucket, "so stripping incorrect leading '/' from", head)
            head = head.lstrip('/')
    
        # strip leading / in head if present
        if bucket and head!="":
            folderOffset = bucket + "/" + head
        elif bucket:
            folderOffset = bucket
        else:
            folderOffset = head

        if schema=='s3' or node.redirect_import_folder_to_s3_path:
            folderURI = "s3://" + folderOffset
            importResult = node.import_s3(bucket, timeoutSecs=timeoutSecs)

        elif schema=='s3n':
            folderURI = "s3n://" + folderOffset
            importResult = node.import_hdfs(folderURI, timeoutSecs=timeoutSecs)

        elif schema=='maprfs':
            folderURI = "hdfs:///" + folderOffset
            importResult = node.import_hdfs(folderURI, timeoutSecs=timeoutSecs)

        elif schema=='hdfs' or node.redirect_import_folder_to_s3n_path:
            h2o.verboseprint(h2o.nodes[0].hdfs_name_node)
            h2o.verboseprint("folderOffset;", folderOffset)
            folderURI = "hdfs://" + h2o.nodes[0].hdfs_name_node + "/" + folderOffset
            importResult = node.import_hdfs(folderURI, timeoutSecs=timeoutSecs)

        else: 
            raise Exception("schema not understood: %s" % schema)

    importPattern = folderURI + "/" + pattern
    return (importResult, importPattern)


# can take header, header_from_file, exclude params
def parse_only(node=None, pattern=None, hex_key=None,
    timeoutSecs=30, retryDelaySecs=0.5, initialDelaySecs=0.5, pollTimeoutSecs=180, noise=None,
    noPoll=False, **kwargs):

    if not node: node = h2o.nodes[0]

    parseResult = node.parse(pattern, hex_key,
        timeoutSecs, retryDelaySecs, initialDelaySecs, pollTimeoutSecs, noise,
        noPoll, **kwargs)

    parseResult['python_source'] = pattern
    return parseResult


def import_parse(node=None, schema='local', bucket=None, path=None,
    src_key=None, hex_key=None, 
    timeoutSecs=30, retryDelaySecs=0.5, initialDelaySecs=0.5, pollTimeoutSecs=180, noise=None,
    noPoll=False, doSummary=False, **kwargs):

    if not node: node = h2o.nodes[0]

    (importResult, importPattern) = import_only(node, schema, bucket, path,
        timeoutSecs, retryDelaySecs, initialDelaySecs, pollTimeoutSecs, noise, 
        noPoll, doSummary, src_key, **kwargs)

    h2o.verboseprint("importPattern:", importPattern)
    h2o.verboseprint("importResult", h2o.dump_json(importResult))

    parseResult = parse_only(node, importPattern, hex_key,
        timeoutSecs, retryDelaySecs, initialDelaySecs, pollTimeoutSecs, noise, 
        noPoll, **kwargs)
    h2o.verboseprint("parseResult:", h2o.dump_json(parseResult))

    # do SummaryPage here too, just to get some coverage
    if doSummary:
        node.summary_page(myKey2, timeoutSecs=timeoutSecs)

    return parseResult


# returns full key name, from current store view
def find_key(filter):
    found = None
    storeViewResult = h2o.nodes[0].store_view(filter=filter)
    keys = storeViewResult['keys']
    if len(keys) == 0:
        return None

    if len(keys) > 1:
        h2o.verboseprint("Warning: multiple imported keys match the key pattern given, Using: %s" % keys[0]['key'])

    return keys[0]['key']


# the storeViewResult for every node may or may not be the same
# supposed to be the same? In any case
def delete_all_keys(node=None, timeoutSecs=30):
    if not node: node = h2o.nodes[0]
    storeViewResult = h2o_cmd.runStoreView(node, timeoutSecs=timeoutSecs)
    keys = storeViewResult['keys']
    for k in keys:
        node.remove_key(k['key'])
    deletedCnt = len(keys)
    print "Deleted", deletedCnt, "keys at", node
    return deletedCnt

def delete_all_keys_at_all_nodes(node=None, timeoutSecs=30):
    if not node: node = h2o.nodes[0]
    totalDeletedCnt = 0
    # do it in reverse order, since we always talk to 0 for other stuff
    # this will be interesting if the others don't have a complete set
    # theoretically, the deletes should be 0 after the first node 
    # since the deletes should be global
    for node in reversed(h2o.nodes):
        deletedCnt = delete_all_keys(node, timeoutSecs=timeoutSecs)
        totalDeletedCnt += deletedCnt
    print "\nTotal: Deleted", totalDeletedCnt, "keys at", len(h2o.nodes), "nodes"
    return totalDeletedCnt
