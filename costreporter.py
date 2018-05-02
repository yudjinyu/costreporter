#----------------------------------------------------------------------------
# Copyright 2018, FittedCloud, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#Unless required by applicable law or agreed to in writing, software
#distributed under the License is distributed on an "AS IS" BASIS,
#WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#See the License for the specific language governing permissions and
#limitations under the License.
#
#Author: Gregory Fedynyshyn (greg@fittedcloud.com)
#----------------------------------------------------------------------------

import sys
import os
import re
import collections
import time
import datetime
import traceback
import argparse
import csv
import json
import boto3
import botocore
import pprint # pretty printing!

from collections import namedtuple

FC_AWS_ENV = "AWS_DEFAULT_PROFILE"

# simple sanity check for start/end dates.  exceptions will occur with anything
# more complicatedly wrong
FC_MATCH_DATE = "[0-9]{4}-[0-1][0-9]-[0-3][0-9]"

# current valid values are MONTHLY and DAILY
FC_INTERVALS = ["MONTHLY", "DAILY"]

# supported RI recommendation services are EC2 and RDS
FC_RI_SERVICES = ["EC2", "RDS"]

# valid commands in the form of {<command name>: <command description>}
FC_COMMANDS = {"cost": "Report cost data", "recommend": "Report reserved instance recommendations", "coverage": "Report reservation coverage"}

# a list of currently available dimensions by which to group
GROUP_DIMENSIONS = ["AZ",
                    "INSTANCE_TYPE",
                    "LINKED_ACCOUNT",
                    "OPERATION",
                    "PURCHASE_TYPE",
                    "REGION",
                    "SERVICE",
                    "USAGE_TYPE",
                    "USAGE_TYPE_GROUP",
                    "RECORD_TYPE",
                    "OPERATING_SYSTEM",
                    "TENANCY",
                    "SCOPE",
                    "PLATFORM",
                    "SUBSCRIPTION_ID",
                    "LEGAL_ENTITY_NAME",
                    "DEPLOYMENT_OPTION",
                    "DATABASE_ENGINE",
                    "CACHE_ENGINE",
                    "INSTANCE_TYPE_FAMILY"]

# We dynamically update regions in our software, but for the
# purposes of this script, hardcoding is fine.
AWS_REGIONS = [
    'us-east-1',       # US East (N. Virginia)
    'us-east-2',       # US East (Ohio)
    'us-west-1',       # US West (N. California)
    'us-west-2',       # US West (Oregon)
    'ca-central-1',    # Canada (Central)
    'eu-central-1',    # EU (Frankfurt)
    'eu-west-1',       # EU (Ireland)
    'eu-west-2',       # EU (London)
    'eu-west-3',       # EU (Paris)
    'ap-northeast-1',  # Asia Pacific (Tokyo)
    'ap-northeast-2',  # Asia Pacific (Seoul)
    'ap-northeast-3',  # Asia Pacific (Osaka-Local)
    'ap-southeast-1',  # Asia Pacific (Singapore)
    'ap-southeast-2',  # Asia Pacific (Sydney)
    'ap-south-1',      # Asia Pacific (Mumbai)
    'sa-east-1',       # South America (Sao Paulo)
]

# array of default abbreviations to use with output
ABBRV = {
    "AWS CloudTrail": "CT",
    "AWS Data Transfer": "DT",
    "AWS Key Management Service": "KMS",
    "AWS Support (Developer)": "SD",
    "Amazon DynamoDB": "DDB",
    "Amazon Elastic Block Store": "EBS",
    "Amazon Elastic Compute Cloud - Compute": "EC2",
    "Amazon Relational Database Service": "RDS",
    "Amazon Simple Email Service": "SES",
    "Amazon Simple Notification Service": "SNS",
    "Amazon Simple Queue Service": "SQS",
    "Amazon Simple Storage Service": "S3",
    "AmazonCloudWatch": "CW",
    "Refund": "Ref" # everyone's favorite
} 

# simple check to see if string can be converted to float
def isfloat(value):
  try:
    float(value)
    return True
  except ValueError:
    return False

# simple abbreviation scheme:
#
# strip off beginning "Amazon" and "AWS" from service name
# then just use remaining uppercase letters to form abbreviation.
# currently not in use
def simple_abbreviation(string, suffix=""):
    abbr = ""
    if string.find("AWS") == 0:
        string = string[3:]
    elif string.find("Amazon") == 0:
        string = string[6:]
    for letter in string:
        if letter.isupper() or letter.isnumeric(): # numerals are okay too
            abbr += letter

    return abbr 

# currently not in use.  originally, would be used to generate abbreviations
# for better printing on the screen, but not really needed.
def build_abbreviations(a, s, r, start, end):
    abbrv = {}

    try:
        ce = boto3.client('ce',
                          aws_access_key_id=a,
                          aws_secret_access_key=s,
                          region_name=r) # not sure if region matters
        res = ce.get_dimension_values(SearchString="",
                                      TimePeriod={"Start":start, "End":end},
                                      Dimension="SERVICE",
                                      Context="COST_AND_USAGE")
        # TODO make sure there are no duplicates
        dims = res['DimensionValues']
        for k in dims:
            ab = simple_abbreviation(k['Value'])
            abbrv[k['Value']] = ab # FIXME duplicates will overwrite values here...
    except:
        e = sys.exc_info()
        print("ERROR: exception region=%s, error=%s" %(r, str(e)))
        traceback.print_exc()
    return abbrv

# "get res recs" uses lookback instead of start/end time.
# currently, supported services are EC2 and RDS
def get_reserve_instance_recs(a, s, service="EC2", lookback="SIXTY_DAYS"):

    if service == "EC2":
        service = "Amazon Elastic Compute Cloud - Compute"
    elif service == "RDS":
        service = "Amazon Relational Database Service"
    ce = boto3.client('ce',
                      aws_access_key_id=a,
                      aws_secret_access_key=s,
                      region_name="us-east-1") # not sure if region matters
    res = ce.get_reservation_purchase_recommendation(
        Service=service,
        LookbackPeriodInDays=lookback,
        TermInYears="ONE_YEAR",
        )
    #pprint.pprint(res, indent=1)
    return res

def get_reservation_coverage(a, s, rlist, start, end, dims, tags, granularity="MONTHLY"):
    covs = []

    groupbys = []
    if len(dims) > 0 or len(tags) > 0:
        dims = dims.split(",")
        for d in dims:
            groupbys.append({"Type":"DIMENSION", "Key":d})

        tags = tags.split(",")
    if len(tags) > 0 and tags != [""]:
        for t in tags:
            groupbys.append({"Type":"TAG", "Key":t})

    if len(groupbys) == 0: # group by service by default
        groupbys.append({"Type":"DIMENSION", "Key":"REGION"})

    try:
        for r in rlist:
            ce = boto3.client('ce',
                              aws_access_key_id=a,
                              aws_secret_access_key=s,
                              region_name=r)

            # can either have granularity or groupby, but not both
            if len(groupbys) > 0:
                res = ce.get_reservation_coverage(TimePeriod={"Start":start, "End":end},
                                                  GroupBy=groupbys)
            else:
                res = ce.get_reservation_coverage(TimePeriod={"Start":start, "End":end},
                                                  Granularity=granularity)
            cbt = res['CoveragesByTime']
            for groups in cbt:
                for group in groups['Groups']:
                    c = {
                        "start_time": groups['TimePeriod']['Start'],
                        "end_time": groups['TimePeriod']['End'],
                        "Attributes": group['Attributes'],
                        "Coverage": group['Coverage']['CoverageHours']
                    }
                    covs.append(c)
    except:
        e = sys.exc_info()
        print("ERROR: exception region=%s, error=%s" %(r, str(e)))
        traceback.print_exc()
    return covs

def get_costs(a, s, rlist, start, end, dims, tags, granularity="MONTHLY"):
    costs = []

    groupbys = []
    if len(dims) > 0 or len(tags) > 0:
        dims = dims.split(",")
        for d in dims:
            groupbys.append({"Type":"DIMENSION", "Key":d})

        tags = tags.split(",")
    if len(tags) > 0 and tags != [""]:
        for t in tags:
            groupbys.append({"Type":"TAG", "Key":t})

    if len(groupbys) == 0: # group by service by default
        groupbys.append({"Type":"DIMENSION", "Key":"SERVICE"})

    try:
        for r in rlist:
            ce = boto3.client('ce',
                              aws_access_key_id=a,
                              aws_secret_access_key=s,
                              region_name=r)


            if len(groupbys) > 0:
                res = ce.get_cost_and_usage(TimePeriod={"Start":start, "End":end},
                                            Granularity=granularity,
                                            Metrics=["BlendedCost", "UnblendedCost", "UsageQuantity"],
                                            GroupBy=groupbys)
            else:
                res = ce.get_cost_and_usage(TimePeriod={"Start":start, "End":end},
                                            Granularity=granularity,
                                            Metrics=["BlendedCost", "UnblendedCost", "UsageQuantity"])
            rbt = res['ResultsByTime']
            for groups in rbt:
                for group in groups['Groups']:
                # Metrics are of {'Amount':xxxxxx, 'Unit':xxxxxx}
                    cost = {
                        "region": r,
                        "estimated": groups['Estimated'],
                        "start_time": groups['TimePeriod']['Start'],
                        "end_time": groups['TimePeriod']['End'],
                        "group": group['Keys'],
                        #"srvabbr": ABBRV[group['Keys'][0]],
                        "blended_cost": group['Metrics']['BlendedCost'],
                        "unblended_cost": group['Metrics']['UnblendedCost'],
                        "usage_quantity": group['Metrics']['UsageQuantity']
                    }
                    costs.append(cost)
    except:
        e = sys.exc_info()
        print("ERROR: exception region=%s, error=%s" %(r, str(e)))
        traceback.print_exc()
    return costs

# we have some nested values in cost so we need to process the data
# before converting to CSV.  takes in dict, returns flattened dict
# dict cannot have lists, just sub-dicts
def flatten(d, parent_key='', sep='_'):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, collections.MutableMapping):
            items.extend(flatten(v, new_key, sep=sep).items())
        else:
            if type(v) == type(list()): # we don't have any lists with > 1 item
                v = v[0]
            items.append((new_key, v))
    return dict(items)

# output is [{'group': 'name', values:{'unblended_cost':xxx, 'unblended_unit':xxx,
#             'usage_quantity':xxx, 'usage_unit':xxx}}]
def consolidate_costs_by_group(costs):
    out = []
    for cost in costs:
        found = 0

        # check if group already exists in list
        for i in range(0, len(out)):
            if out[i]['group'] == cost['group'][0]:
                found = 1
                out[i]['values']['unblended_cost'] += \
                        float(cost['unblended_cost']['Amount'])
                out[i]['values']['usage_quantity'] += \
                        float(cost['usage_quantity']['Amount'])
                break
        # else add to output
        if found == 0:
            tmp = {'group':cost['group'][0], 'values':{}}
            tmp['values'] = {'unblended_cost': float(cost['unblended_cost']['Amount']),
                             'unblended_unit': cost['unblended_cost']['Unit'],
                             'usage_quantity': float(cost['usage_quantity']['Amount']),
                             'usage_unit': cost['usage_quantity']['Unit']}
            out.append(tmp)
    return out

# pass return value from get_reserve_instance_recs
def print_ri_recs_results(recs, use_json=False, use_csv=False, lookback="SIXTY_DAYS", term="ONE_YEAR"):
    if len(recs) == 0:
        return

    if use_json == True:
        print(json.dumps(recs, sort_keys=True, indent=4))
    elif use_csv == True:
        #TODO the recommendation output is very nested, not ideal for CSV
        pass
    else:
        print("Reserved Instance Recommendations: %s\n" %recs["Metadata"]["GenerationTimestamp"])
        print(" = Recommendation Details =")
        for rec in recs["Recommendations"]:
            for detail in rec["RecommendationDetails"]:
                for key, value in detail.items():
                    if key == "InstanceDetails":
                        continue # we'll print this out later
                    if isfloat(value): # if a float
                        print("%-54s %14.2f" %(key, float(value)))
                    else:
                        print("%-54s %14s" %(key, str(value)))

                print("\n = Instance Details =")
                for key, value in detail["InstanceDetails"].items():
                    print("%s:" %key)
                    for k, v in detail["InstanceDetails"][key].items():
                        if isfloat(v): # if a float
                            print("%-54s %14.2f" %(k, float(v)))
                        else:
                            print("%-54s %14s" %(k, str(v)))

            print("\n = Recommendation Summary =")
            for key, value in rec["RecommendationSummary"].items():
                if isfloat(value): # if a float
                    print("%-54s %14.2f" %(key, float(value)))
                else:
                    print("%-54s %14s" %(key, str(value)))

# pass return value from get_reservation_coverages()
def print_coverage_results(covs, use_json=False, use_csv=False, start=None, end=None):
    if len(covs) == 0:
        return

    if use_json == True:
        print(json.dumps(covs, sort_keys=True, indent=4))
    elif use_csv == True:
        flat_covs = []
        for cov in covs:
            flat_covs.append(flatten(cov))
        # print headers
        csv_writer = csv.DictWriter(sys.stdout, flat_covs[0].keys(), delimiter=",")
        csv_writer.writeheader()
        for cov in flat_covs:
            csv_writer.writerow(cov)
    else:
        # for calculating totals
        totals = {}

        print("\nSummary of Reservation Coverage: %s - %s\n" %(start, end))
        # print header.  hard-coded for now
        for cov in covs:
            print("= Group Attributes =")
            for k, v in cov['Attributes'].items():
                print("    %s: %s" %(k, v))
            print("= Coverage =")
            for k, v in cov['Coverage'].items():
                if k in totals:
                    totals[k] += float(v)
                else:
                    totals[k] = float(v)
                print("    %-50s\t%14.2f" %(k, float(v)))
            print("")
        print("= Totals =")
        for k, v in totals.items():
            print("%-54s\t%14.2f" %(k, v))

# pass return value from get_costs()
def print_cost_results(costs, use_json=False, use_csv=False, start=None, end=None):
    if len(costs) == 0:
        return

    if use_json == True:
        print(json.dumps(costs, sort_keys=True, indent=4))
    elif use_csv == True:
        flat_costs = []
        for cost in costs:
            flat_costs.append(flatten(cost))

        # print headers
        #    print(
        csv_writer = csv.DictWriter(sys.stdout, flat_costs[0].keys(), delimiter=",")
        csv_writer.writeheader()
        for cost in flat_costs:
            csv_writer.writerow(cost)
    else:
        out = consolidate_costs_by_group(costs)
        print("\nSummary of costs: %s - %s\n" %(start, end))
        # print header.  hard-coded for now
        print("%s %61s" %("= Group =", "= Cost ="))
        for cost in out:
            print("%-54s\t%14.2f %s"          \
                  %(cost['group'],
                  cost['values']['unblended_cost'],
                  cost['values']['unblended_unit']))

# human-readable option currently not used, so hide it from usage
def print_usage():
     print("costreporter.py <command> [options]\n")

     print("    Command must be one of the following:\n")
     for cmd, desc in FC_COMMANDS.items():
         print("    %s - %s" %(cmd, desc))
     print("\n    General options are:\n\n"
           "        -h --help - Display this help message\n"
           "        -p --profile <profile name> - AWS profile name\n"
           "                (can be used instead of -a and -s options)\n"
           "        -a --accesskey <access key> - AWS access key\n"
           "        -s --secretkey <secret key> - AWS secret key\n"
           #"       -r --regions <region1,region2,...> - A list of AWS regions.  If this option is omitted, all regions will be checked.\n" # currently not in use
           "        -j --json - Output in JSON format.\n"
           "        -c --csv - Output as CSV.  Not compatible with --json\n"
           "                (currently not available for 'recommend' command).\n")
     print("    Options for 'cost' and 'coverage' commands:\n\n"
           "        -t --timerange - Time range as <start,end> time\n"
           "                in format <YYYY-MM-DD>,<YYYY-MM-DD> (required)\n"
           "        -d --dimension <dimension> - Group output by dimension\n"
           "                (examples: AZ,INSTANCE_TYPE,LINKED_ACCOUNT,OPERATION,\n"
           "                 PURCHASE_TYPE,REGION,SERVICE (default),USAGE_TYPE,\n"
           "                 USAGE_TYPE_GROUP,RECORD_TYPE,OPERATING_SYSTEM,\n"
           "                 TENANCY,SCOPE,PLATFORM,SUBSCRIPTION_ID,LEGAL_ENTITY_NAME,\n"
           "                 DEPLOYMENT_OPTION,DATABASE_ENGINE,CACHE_ENGINE,\n"
           "                 INSTANCE_TYPE_FAMILY)\n"
           "        -g --tag <tag name> - Group by tag name\n"
           "                (list of names in format Tag1,Tag2,...,TagN).\n"
           "        -i --interval <interval> - Dumps stats at <interval> granularity.\n"
           "                Valid values are MONTHLY (default) and DAILY.\n")
     print("    Options for 'recommend' command:\n\n"
           "        -l --lookback <lookback> - Lookback period for recommendations.\n"
           "                Valid values are SEVEN_DAYS, THIRTY_DAYS,\n"
           "                SIXTY_DAYS (default)\n"
           "        -r --service <service> - Service for recommendations.\n"
           "                Valid values are EC2 (default) and RDS\n")
           #"    -b --abbrv - Output service abbreviations.\n\n"
     print("    One of the following three parameters are required:\n"
           "        1. Both the -a and -s options.\n"
           "        2. The -p option.\n"
           "        3. A valid " + FC_AWS_ENV + " environment variable.")

def parse_options(argv):
    parser = argparse.ArgumentParser(prog="costreporter.py",
                     add_help=False) # use print_usage() instead

    parser.add_argument("-p", "--profile", type=str, required=False)
    parser.add_argument("-a", "--access-key", type=str, required=False)
    parser.add_argument("-s", "--secret-key", type=str, required=False)
    parser.add_argument("-z", "--regions", type=str, default="") #dummy
    parser.add_argument("-t", "--timerange", type=str, default="dummy,dummy")
    parser.add_argument("-j", "--json", action="store_true", default=False)
    parser.add_argument("-c", "--csv", action="store_true", default=False)
    parser.add_argument("-d", "--dimension", type=str, default="")
    parser.add_argument("-g", "--tag", type=str, default="")
    parser.add_argument("-i", "--interval", type=str, default="MONTHLY")
    parser.add_argument("-l", "--lookback", type=str, default="SIXTY_DAYS")
    parser.add_argument("-r", "--service", type=str, default="EC2")

    args = parser.parse_args(argv)
    if (len(args.regions) == 0):
        return args.profile, args.access_key, args.secret_key, [], args.timerange, args.json, args.csv, args.dimension, args.tag, args.interval, args.lookback, args.service
    else:
        return args.profile, args.access_key, args.secret_key, args.regions.split(','), args.timerange, args.json, args.csv, args.dimension, args.tag, args.interval, args.lookback, args.service


def parse_args(argv):
    # ArgumentParser's built-in way of automatically handling -h and --help
    # leaves much to be desired, so using this hack instead.
    for arg in argv:
        if arg == '--help' or arg == '-h':
            print_usage()
            os._exit(0)

    cmd = argv[1]

    p, a, s, rList, t, j, c, d, g, i, l, r = parse_options(argv[2:])

    return cmd, p, a, s, rList, t, j, c, d, g, i, l, r


if __name__ == "__main__":
    cmd, p, a, s, rList, t, j, c, d, g, i, l, r = parse_args(sys.argv)

    if cmd not in FC_COMMANDS.keys():
        print_usage()
        print("\nError: invalid command %s" %cmd)
        os._exit(1)

    # need either -a and -s, -p, or AWS_DEFAULT_PROFILE environment variable
    if not a and not s and not p:
        if (FC_AWS_ENV in os.environ):
            p = os.environ[FC_AWS_ENV]
        else:
            print_usage()
            print("\nError: must provide either -p option or -a and -s options")
            os._exit(1)

    if a and not s and not p:
        print_usage()
        print("\nError: must provide secret access key using -s option")
        os._exit(1)

    if not a and s and not p:
        print_usage()
        print("\nError: must provide access key using -a option")
        os._exit(1)

    if p:
        try:
            home = os.environ["HOME"]
            pFile = open(home + "/.aws/credentials", "r")
            line = pFile.readline()
            p = "["+p+"]"
            while p not in line:
                line = pFile.readline()
                if (line == ""): # end of file
                    print_usage()
                    print("\nError: invalid profile: %s" %p)
                    os._exit(1)

            # get access/secret keys
            for _dummy in range(0, 2):
                line = pFile.readline()
                if "aws_secret_access_key" in line:
                    s = line.strip().split(" ")[2]
                elif "aws_access_key_id" in line:
                    a = line.strip().split(" ")[2]

        except:
            print("Error: reading credentials for profile %s." %p)
            os._exit(1)

    #if (len(rList) == 0):
    #    rList = AWS_REGIONS
    # values are not divided by region, users should instead use -d REGION
    # option if they want to group results by region
    rList = ["us-east-1"] # just use arbitrary region

    if j == True and c == True:
        print("Error: cannot specify both -j and -c")
        os._exit(1)

    time = t.split(",")

    # simple sanity check #1
    if len(time) != 2 and cmd != "recommend":
        print("Error: proper timerange format for <start,end> times is <YYYY-MM-DD>,<YYYY-MM-DD>")
        os._exit(1)

    start_time = time[0]
    end_time = time[1]

    # simple sanity check #2
    if cmd != "recommend" and                          \
       (re.match(FC_MATCH_DATE, start_time) == None or \
       re.match(FC_MATCH_DATE, end_time) == None):
        print("start_time = %s, match = %s" %(start_time, re.match(FC_MATCH_DATE, start_time)))
        print("end_time = %s, match = %s" %(end_time, re.match(FC_MATCH_DATE, end_time)))
        print("Error: proper timerange format for start, end times is <YYYY-MM-DD>,<YYYY-MM-DD>")
        os._exit(1)

    # simple sanity check for dimensions
    if d != "":
        dtmp = d.split(",")
        for dt in dtmp:
            if dt not in GROUP_DIMENSIONS:
                print("Error: invalid dimension: %s" %str(dt))
                os._exit(1)

    if i not in FC_INTERVALS:
        print("Error: invalid time interval: %s" %str(i))
        os._exit(1)

    # finally, let's get some cost data!
    try:
        # comment out customer service abbreviations for now
        #abbrv = build_abbreviations(a, s, rList[0], start_time, end_time)
        #ABBRV.update(abbrv)

        if cmd == "cost":
            costs = get_costs(a, s, rList, start_time, end_time, d, g, i)
            print_cost_results(costs, j, c, start_time, end_time)
        elif cmd == "recommend":
            recs = get_reserve_instance_recs(a, s, r, l)
            print_ri_recs_results(recs)
        elif cmd == "coverage":
            covs = get_reservation_coverage(a, s, rList, start_time, end_time, d, g, i)
            print_coverage_results(covs, j, c, start_time, end_time)
    except:
        e = sys.exc_info()
        traceback.print_exc()
        os._exit(1)
