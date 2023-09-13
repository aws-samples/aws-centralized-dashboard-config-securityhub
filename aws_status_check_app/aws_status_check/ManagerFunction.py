# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import boto3
from botocore.config import Config
import os
import time

class Manager(object):

    """Checks status of AWSConfigRecorders in accounts"""
    def __init__(self):

        self.config = Config(
        signature_version='v4',
        retries={
            'max_attempts': 10,
            'mode': 'standard',
        }
        )
        self.region = os.environ['AWS_REGION']
        self.org = boto3.client('organizations', config=self.config, region_name=self.region)
        self.cloudwatch_events = boto3.client('events', config=self.config, region_name=self.region)
        self.ssm = boto3.client('ssm', config=self.config, region_name=self.region)
        self.cloudwatch = boto3.client('cloudwatch', config=self.config, region_name=self.region)

    def getStatus(self):
        ssm_parameter_check = self.ssm.get_parameter(Name='/status_check_app/CheckAllAccountsinOrg', WithDecryption=True)
        if ssm_parameter_check['Parameter']['Value'] == 'true':
            self.GetAccountsListfromOrg()
        else:
            self.GetAccountsListfromSSM()

    def GetAccountsListfromOrg(self):

        self.accounts = [accounts['Id'] for accounts in self.org.list_accounts()['Accounts']]
        print('Accounts from Org:', self.accounts)
        self.PublishEventsForEachAccount()

    def GetAccountsListfromSSM(self):

        ssm_parameter_accountid = self.ssm.get_parameter(Name='/status_check_app/AccountIds', WithDecryption=True)
        ssmaccounts = ssm_parameter_accountid['Parameter']['Value']
        self.accounts = ssmaccounts.split(",")
        print('Accounts from SSM:', self.accounts)
        self.PublishEventsForEachAccount()

    def PublishEventsForEachAccount(self):

        for self.accountid in self.accounts:

            jsonstr={}
            jsonstr["aws_status_check_account"]=self.accountid
            print("aws_status_check_account:", jsonstr)
            event_bus_arn = "arn:aws:events:" + self.region + ":" + aws_account_id + ":event-bus/default"
            response = self.cloudwatch_events.put_events(
            Entries=[
            {
                "Detail": json.dumps(jsonstr),
                "DetailType": "aws_status_check_event",
                "EventBusName": event_bus_arn,
                "Resources": [
                    lambda_function_arn
            ],
            "Source": "aws_status_check_app.ManagerFn"
            }
            ])
            print("response", response)

        response = self.cloudwatch.put_metric_data(
            MetricData=[
                {
                    'MetricName': 'TotalAccountsMonitoredForAWSConfig',
                    'Value': len(self.accounts)
                }
            ],
            Namespace='CustomMetrics/Config'
        )

def lambda_handler(event, context):
    global lambda_function_arn
    global aws_account_id

    lambda_function_arn = context.invoked_function_arn
    aws_account_id = context.invoked_function_arn.split(":")[4]

    statuscheckapp = Manager()
    _start = time.time()
    statuscheckapp.getStatus()
    print("Sequential execution time: %s seconds", time.time() - _start)
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            "Response ": "SUCCESS"
        }, default=str)
    }