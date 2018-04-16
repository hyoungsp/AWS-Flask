import uuid
import json
import hashlib, hmac
import base64
import os
from os import path
import subprocess
from shutil import copyfile
import boto3
from botocore.exceptions import ClientError
import datetime
from flask import Flask, request, Response, jsonify, render_template

app = Flask(__name__)

job_ids_filenames = {} #global dictionary that holds job id

s3 = boto3.resource('s3')

def home():
    return "MPCS Cloud Computing GAS App."

@app.route('/hello', methods=['GET'])
def hello():
    return "West of House hyoungsun! <br ><br />&gt; _"


''' Exercise 1. & 3. '''
# sign key function
def sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
# hasing the key with hex
def get_signature(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()
# generating a key with private key and other arguments
def getSignatureKey(key, dateStamp, regionName, serviceName):
    kDate = sign(("AWS4" + key).encode("utf-8"), dateStamp)
    kRegion = sign(kDate, regionName)
    kService = sign(kRegion, serviceName)
    kSigning = sign(kService, "aws4_request")
    return kSigning

@app.route('/annotate', methods=['GET'])
def post_to_s3():
    unique_id = str(uuid.uuid4())
    time_now = datetime.datetime.utcnow()
    time_expiration = time_now + datetime.timedelta(minutes=20)
    time_exp_iso = time_expiration.strftime("%Y-%m-%dT%H:%M:%SZ")

    # retrieving public and private key from the credentials file
    f = open('../credentials')
    lines = f.readlines()
    public_key, private_key = lines[0].split("=")[1].strip(), lines[1].split("=")[1].strip()

    # define a policy
    s3_policy = str(json.dumps({
        "expiration": time_exp_iso,
        "conditions": [
            {"bucket": "gas-inputs"},
            ["starts-with", "$key", "hyoungsun/"],
            {"acl": "private"},
            ["starts-with", "$Content-Type", "multipart/form-data"],
            {"x-amz-meta-uuid": unique_id},
            {"x-amz-server-side-encryption": "AES256"},
            {"x-amz-credential": public_key + "/" + time_now.strftime("%Y%m%d") + "/us-east-1/s3/aws4_request"},
            {"x-amz-algorithm": "AWS4-HMAC-SHA256"},
            {"x-amz-date": time_now.strftime("%Y%m%dT%H%M%SZ")},
            ["starts-with", "$success_action_redirect", "http://hyoungsun-hw3.ucmpcs.org:5000/annotate/files"]
        ]
    }))

    # encoding s3_policy with base64
    s3_policy_encoded = base64.b64encode(bytearray(s3_policy, 'utf-8')).decode()

    # creading a signing key and generate a signature
    sign_key = getSignatureKey(private_key, time_now.strftime("%Y%m%d"), "us-east-1", "s3")
    signature = get_signature(sign_key, s3_policy_encoded)

    # render template with annotate.html
    return render_template("annotate.html",
                            s3_acl = "private",
                            bucket_name = "gas-inputs",
                            s3_file = "hyoungsun/" + unique_id + "~${filename}",
                            s3_uuid = unique_id,
                            s3_credential = public_key + "/" + time_now.strftime("%Y%m%d") + "/us-east-1/s3/aws4_request",
                            s3_sig = signature,
                            s3_pol = s3_policy_encoded,
                            s3_date = time_now.strftime("%Y%m%dT%H%M%SZ"))

''' Exercise 2.'''
@app.route('/annotate/files', methods=['GET'])
def get_s3_files():
    # creating s3_files list to holds all files uploaded onto s3
    s3_files = []
    my_bucket = s3.Bucket('gas-inputs')
    for object in my_bucket.objects.filter(Prefix="hyoungsun/"):
        s3_files.append(object.key)
    # render template with table.html
    return render_template("table.html", saved_files = s3_files)
    # return json.dumps({'code': 200,
    #                     'data': {'files': s3_files}
    #                     })


''' Below routes are from hw2 '''
@app.route('/annotations', methods=['POST'])
def request_post():
    file_name = request.args.get("file_name") # get file_name as a key
    if file_name is None: # if the file_name is none, then return jason with bad request
        return json.dumps({'code': 400, 'error': 'The file is not supported'})
    elif file_name and os.path.isfile("../anntools/data/" + file_name):
        new_id = str(uuid.uuid1()) # create uuid
        job_ids_filenames[new_id] = file_name # put the new generated uuid into the global dictionary
        folder_address = "../anntools/data/" + new_id
        try:
            os.makedirs(folder_address) # and then make a foler inside the anntools/data for later use (keep track of uuid)
        except OSError as err:
            print(err)

        full_file_path = folder_address + '/' + file_name
        print(full_file_path)
        copyfile("../anntools/data/"+file_name, full_file_path) # I am copying the file_name (free_2.vcf) into the uuid folder
        sub_process = subprocess.Popen(['python', 'run.py', 'data/' + new_id + '/' + file_name], cwd = "../anntools/")
        # after the subprocess (run.py onto the file_name) - then the uuid folder has three files: file_name, annot.vcf, and log.count
        return json.dumps({'code': 201,
                            'data': {'job_id': new_id,
                                     'input_file': file_name}
                            })
    else:
        return json.dumps({'code': '400 Bad Request', 'error': 'The file not exist'})


@app.route('/annotations/<string:job_id>', methods=['GET'])
def request_get_job(job_id):
    print(job_id)
    if job_id in job_ids_filenames:
        input_file = job_ids_filenames[job_id]
        # get the file path where uuid folder has count.log file in it
        file_path = '../anntools/data/' + job_id + '/' + input_file + '.count.log'
        if os.path.isfile(file_path):
            with open(file_path, 'r') as logfile:
                log_content = logfile.read()
            # after read the logfile then return the json with code of 200
            return json.dumps({'code': 200,
                               'data': {'job_id': job_id,
                                        'log': log_content}
                                })
        else:
            return json.dumps({'code': 400, 'error': 'The job id  does not exist'})


@app.route('/annotations', methods=['GET'])
def request_get_everything():
    #create a list that holds all job ids
    all_jobs = []
    for job in job_ids_filenames.keys():
        all_jobs.append({'job_id': job,
                         'href': 'http://hyoungsun-hw2.ucmpcs.org:5000/annotations/'+ job})
    # after looping through the all_jobs then return all of the contents of the job ids
    return json.dumps({'code': app.make_response(str()).status_code,
                       'data': {'jobs': all_jobs}
                       })


''' Testing for the hw3'''
@app.route('/name', methods=['GET'] )
def display_form():
    return  render_template('test.html')

@app.route('/name', methods=['POST'] )
def process_form():
    name = request.form['username']
    return render_template('test.html', username=name)



app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=True)
# app.run(host='0.0.0.0', debug=True)
