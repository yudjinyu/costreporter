Cost Reporter (Python 2.7)

[This utility was written by FittedCloud](https://www.fittedcloud.com)

For more information about the software, see the following blog posts:

[An Open Source Tool Using AWS Cost Explorer APIs for Reporting RI Recommendations, RI Coverage](https://www.fittedcloud.com/blog/open-source-tool-using-aws-cost-explorer-apis-reporting-ri-recommendations-ri-coverage/)

[An Open Source tool using AWS Cost Explorer APIs for Reporting AWS Costs](https://www.fittedcloud.com/blog/open-source-tool-reporting-aws-costs/)


Installation:
    1. Install Python 2.7 and pip2.7 if not already installed.
    2. Install boto3 and botocore.  Use "sudo pip2.7 install boto3 botocore".

Quick Start:
```
$ # display cost information
$ python costreporter.py cost -a <aws access key> -s <aws secret key> -t <start-time as, YYYY-MM-DD>,<end-time as YYYY-MM-DD>
$
$ # display reserved instance recommendations
$ python costreporter.py recommend -a <aws access key> -s <aws secret key>
$
$ # display reservation coverage
$ python costreporter.py cost -a <aws access key> -s <aws secret key> -t <start-time as, YYYY-MM-DD>,<end-time as YYYY-MM-DD>
```
For more information about options:
```
$ python costreporter.py -h
costreporter.py <command> [options]

    Command must be one of the following:

    cost - Report cost data
    coverage - Report reservation coverage
    recommend - Report reserved instance recommendations

    General options are:

        -h --help - Display this help message
        -p --profile <profile name> - AWS profile name
                (can be used instead of -a and -s options)
        -a --accesskey <access key> - AWS access key
        -s --secretkey <secret key> - AWS secret key
        -j --json - Output in JSON format.
        -c --csv - Output as CSV.  Not compatible with --json
                (currently not available for 'recommend' command).

    Options for 'cost' and 'coverage' commands:

        -t --timerange - Time range as <start,end> time
                in format <YYYY-MM-DD>,<YYYY-MM-DD> (required)
        -d --dimension <dimension> - Group output by dimension
                (examples: AZ,INSTANCE_TYPE,LINKED_ACCOUNT,OPERATION,
                 PURCHASE_TYPE,REGION,SERVICE (default),USAGE_TYPE,
                 USAGE_TYPE_GROUP,RECORD_TYPE,OPERATING_SYSTEM,
                 TENANCY,SCOPE,PLATFORM,SUBSCRIPTION_ID,LEGAL_ENTITY_NAME,
                 DEPLOYMENT_OPTION,DATABASE_ENGINE,CACHE_ENGINE,
                 INSTANCE_TYPE_FAMILY)
        -g --tag <tag name> - Group by tag name
                (list of names in format Tag1,Tag2,...,TagN).
        -i --interval <interval> - Dumps stats at <interval> granularity.
                Valid values are MONTHLY (default) and DAILY.

    Options for 'recommend' command:

        -l --lookback <lookback> - Lookback period for recommendations.
                Valid values are SEVEN_DAYS, THIRTY_DAYS,
                SIXTY_DAYS (default)
        -r --service <service> - Service for recommendations.
                Valid values are EC2 (default) and RDS

    One of the following three parameters are required:
        1. Both the -a and -s options.
        2. The -p option.
        3. A valid AWS_DEFAULT_PROFILE environment variable.
```
