# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import boto3
from botocore.config import Config
import time
import os

class Worker(object):

    def __init__(self, accountid):

        self.accountid = accountid
        self.config = Config(
            signature_version='v4',
            retries={
                'max_attempts': 10,
                'mode': 'standard',
            }
        )
        self.region = os.environ['AWS_REGION']
        self.sts_connection = boto3.client(
            'sts', config=self.config, region_name=self.region)
        self.cloudwatch = boto3.client(
            'cloudwatch', config=self.config, region_name=self.region)
        self.AWSConfigRecordersTotal = 0
        self.AWSConfigRecordersEnabled = 0

    def GetRegionsfromAccount(self):

        print("account:", self.accountid)
        acct_b = self.sts_connection.assume_role(
            RoleArn="arn:aws:iam::" + self.accountid + ":role/AssumedFunctionRole",
            RoleSessionName="cross_acct_lambda"
        )
        self.ACCESS_KEY = acct_b['Credentials']['AccessKeyId']
        self.SECRET_KEY = acct_b['Credentials']['SecretAccessKey']
        self.SESSION_TOKEN = acct_b['Credentials']['SessionToken']

        self.ec2 = boto3.client(
            'ec2',
            aws_access_key_id=self.ACCESS_KEY,
            aws_secret_access_key=self.SECRET_KEY,
            aws_session_token=self.SESSION_TOKEN,
            config=self.config
        )

        filters = [
            {
                'Name': 'opt-in-status',
                'Values': ['opt-in-not-required', 'opted-in']
            }
        ]

        self.regions = [region['RegionName'] for region in self.ec2.describe_regions(
            Filters=filters)['Regions']]

        self.PublishConfigStatustoCloudwatchforEveryRegion()
        self.PublishSecurityHubScoretoCloudWatchForEveryRegion()

    def PublishConfigStatustoCloudwatchforEveryRegion(self):

        for self.currentregion in self.regions:

            awsconfig = boto3.client(
                'config',
                aws_access_key_id=self.ACCESS_KEY,
                aws_secret_access_key=self.SECRET_KEY,
                aws_session_token=self.SESSION_TOKEN,
                region_name=self.currentregion,
                config=self.config
            )
            try:
                self.config_recorder_response = awsconfig.describe_configuration_recorder_status()
                print("region:", self.currentregion)
                response = self.config_recorder_response["ConfigurationRecordersStatus"]
                print("Config Enabled:", len(response))
                if len(response) > 0:
                    index = 0
                    self.AWSConfigRecordersTotal += 1
                    print("Value of recording:", response[index]['recording'])
                    if response[index]['recording'] == True:
                        print("PUBLISHING CONFIG RECORDER SUCCESS")
                        self.AWSConfigRecordersEnabled += 1
                        response = self.cloudwatch.put_metric_data(
                            MetricData=[
                                {
                                    'MetricName': 'ConfigRecordersStatus',
                                    'Dimensions': [
                                        {
                                        'Name': "AccountId",
                                        'Value': str(self.accountid)
                                    },
                                        {
                                        'Name': "Region",
                                        'Value': self.currentregion
                                    },
                                        ],
                                    'Value': 1
                                },
                            ],
                            Namespace='CustomMetrics/Config'
                        )

                        #Reading Conformance Pack Scores and publishing them to cloudwatch
                        self.conformance_pack_compliance_scores = awsconfig.list_conformance_pack_compliance_scores()
                        print("PUBLISHING ConformancePackComplianceScore for" , self.currentregion , " and accountid ", self.accountid )
                        for score in self.conformance_pack_compliance_scores['ConformancePackComplianceScores']:
                           self.cloudwatch.put_metric_data(
                                Namespace='CustomMetrics/Config',
                                MetricData=[
                                    {
                                        'MetricName': 'ConformancePackComplianceScore',
                                        'Dimensions': [

                                            {
                                                'Name': "AccountId",
                                                'Value': str(self.accountid)
                                            },
                                            {
                                                'Name': "Region",
                                                'Value': self.currentregion
                                            },
                                            {
                                                'Name': "ConformancePackName",
                                                'Value': score['ConformancePackName']
                                            },
                                        ],
                                        'Unit': 'Percent',
                                        'Value': float(score['Score'])
                                    },
                                ]
                            )

                    else:
                        print("CONFIG RECORDER FAILURE - NOT RECORDING- PUBLISHING CONFIG RECORDER FAILURE")
                        response = self.cloudwatch.put_metric_data(
                            MetricData=[
                                {
                                    'MetricName': 'ConfigRecordersStatus',
                                    'Dimensions': [
                                        {
                                        'Name': "AccountId",
                                        'Value': str(self.accountid)
                                        },
                                        {
                                        'Name': "Region",
                                        'Value': self.currentregion
                                        },
                                    ],
                                    'Value': 0
                                },
                            ],
                            Namespace='CustomMetrics/Config'
                        )
            except Exception as e:
                print(e)


        print("PUBLISHING SUMMARY")
        cloudwatch = boto3.client(
            'cloudwatch', config=self.config, region_name=self.region)
        response = cloudwatch.put_metric_data(
            MetricData=[
                {
                    'MetricName': 'TotalAWSConfigRecordersEnabled',
                    'Dimensions': [
                        {
                        'Name': "AccountId",
                        'Value': str(self.accountid)
                        }
                    ],
                    'Value': self.AWSConfigRecordersTotal
                }
            ],
            Namespace='CustomMetrics/Config'
        )
        response = cloudwatch.put_metric_data(
            MetricData=[
                {
                    'MetricName': 'TotalRegions',
                    'Dimensions': [
                        {
                        'Name': "AccountId",
                        'Value': str(self.accountid)
                        }
                    ],
                    'Value': len(self.regions)
                }
            ],
            Namespace='CustomMetrics/Config'
        )
        response = self.cloudwatch.put_metric_data(
            MetricData=[
                {
                    'MetricName': 'ConfigRecordersRunning',
                    'Dimensions': [
                        {
                        'Name': "AccountId",
                        'Value': str(self.accountid)
                        }
                    ],
                    'Value': self.AWSConfigRecordersEnabled
                }
            ],
            Namespace='CustomMetrics/Config'
        )

    def get_standards_status(self, clientSh, accountId):
        filters = {'AwsAccountId': [{'Value': accountId, 'Comparison': 'EQUALS'}],
                'ProductName': [{'Value': 'Security Hub', 'Comparison': 'EQUALS'}],
                'RecordState': [{'Value': 'ACTIVE', 'Comparison': 'EQUALS'}]}

        pages = clientSh.get_paginator('get_findings').paginate(Filters=filters, MaxResults=100)
        standardsDict = {}

        for page in pages:
            for finding in page['Findings']:
                standardsDict = self.build_standards_dict(finding, standardsDict)
        return standardsDict

    def build_standards_dict(self,finding, standardsDict):
        if any(x in json.dumps(finding) for x in ['Compliance', 'ProductFields']):
            if 'Compliance' in finding:
                status = finding['Compliance']['Status']
                prodField = finding['ProductFields']
                if (finding['RecordState'] == 'ACTIVE' and finding['Workflow']['Status'] != 'SUPPRESSED'):  # ignore disabled controls and suppressed findings
                    control = None
                    # get values, json differnt for controls...
                    if 'StandardsArn' in prodField:  # for aws fun
                        control = prodField['StandardsArn']
                        rule = prodField['ControlId']
                    elif 'StandardsGuideArn' in prodField:  # for cis fun
                        control = prodField['StandardsGuideArn']
                        rule = prodField['RuleId']
                    #ignore custom findings
                    if control is not None:
                        controlName = control.split('/')[1]  # get readable name from arn
                        if controlName not in standardsDict:
                            standardsDict[controlName] = {rule: status} # add new in
                        elif not (rule in standardsDict[controlName] and (status == 'PASSED')):  # no need to update if passed
                            standardsDict[controlName][rule] = status
        return standardsDict

    def generateScore(self,standardsDict):
        resultDict = {}
        for control in standardsDict:
            passCheck = 0
            totalControls = len(standardsDict[control])
            passCheck = len({test for test in standardsDict[control] if standardsDict[control][test] == 'PASSED'})

            # generate score
            score = round(passCheck/totalControls * 100)  # generate score
            resultDict[control] = {"Score": score} #build dictionary
        return resultDict

    def PublishSecurityHubScoretoCloudWatchForEveryRegion(self):

        for self.currentregion in self.regions:

            shclient = boto3.client(
                'securityhub',
                aws_access_key_id=self.ACCESS_KEY,
                aws_secret_access_key=self.SECRET_KEY,
                aws_session_token=self.SESSION_TOKEN,
                region_name=self.currentregion,
                config=self.config
            )

            print("GETTING SH SCORE FOR " , self.currentregion , " and accountid ", self.accountid )

            try:

                scores = self.generateScore(self.get_standards_status(shclient, self.accountid))

                print("Account " , self.accountid, " subscribed to AWS Security Hub in region:" + self.currentregion)
                response = self.cloudwatch.put_metric_data(
                    MetricData=[
                        {
                            'MetricName': 'SecurityHubEnabled',
                            'Dimensions': [
                                {
                                'Name': "AccountId",
                                'Value': str(self.accountid)
                                },
                                {
                                'Name': "Region",
                                'Value': self.currentregion
                                },
                            ],
                            'Value': 1
                        },
                    ],
                    Namespace='CustomMetrics/SecurityHub'
                )

                for standard, score_data in scores.items():

                    standard_name = standard
                    score = score_data['Score']
                    print("PUBLISHING SCORE FOR " , self.currentregion , " and accountid ", self.accountid, " ", standard_name," " ,score )
                    response = self.cloudwatch.put_metric_data(
                        MetricData=[
                            {
                                'MetricName': 'SecurityScore',
                                'Dimensions': [
                                    {
                                    'Name': "AccountId",
                                    'Value': str(self.accountid)
                                    },
                                    {
                                    'Name': "Region",
                                    'Value': self.currentregion
                                    },
                                    {
                                    'Name': "StandardName",
                                    'Value': standard_name
                                    },
                                ],
                                'Value': score
                            },
                        ],
                        Namespace='CustomMetrics/SecurityHub'
                    )


            except Exception as e:
                print("Account " , self.accountid, " is not subscribed to AWS Security Hub in region:" + self.currentregion)
                response = self.cloudwatch.put_metric_data(
                    MetricData=[
                        {
                            'MetricName': 'SecurityHubEnabled',
                            'Dimensions': [
                                {
                                'Name': "AccountId",
                                'Value': str(self.accountid)
                                },
                                {
                                'Name': "Region",
                                'Value': self.currentregion
                                },
                            ],
                            'Value': 0
                        },
                    ],
                    Namespace='CustomMetrics/SecurityHub'
                )
                print(e)


def lambda_handler(event, context):

    _start = time.time()
    print("Received Event:", event["detail"]["aws_status_check_account"])
    accid = event["detail"]["aws_status_check_account"]
    awsstatuscheck = Worker(accid)
    awsstatuscheck.GetRegionsfromAccount()
    print("Sequential execution time: %s seconds",
            time.time() - _start)
    # TODO implement
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            "Response ": "SUCCESS"
        }, default=str)
    }
