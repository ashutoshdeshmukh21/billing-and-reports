import boto3
from datetime import datetime, timedelta
from collections import defaultdict

# Function to send email
def send_email(subject, body, sender, recipient):
    AWS_REGION = "us-east-1"
    CHARSET = "UTF-8"
    client = boto3.client('ses', region_name=AWS_REGION)
    response = client.send_email(
        Destination={
            'ToAddresses': [recipient],
        },
        Message={
            'Body': {
                'Html': {
                    'Charset': CHARSET,
                    'Data': body,
                }
            },
            'Subject': {
                'Charset': CHARSET,
                'Data': subject,
            },
        },
        Source=sender,
    )
    return response

# Function to convert usage to bytes
def convert_usage_to_bytes(usage, unit):
    units = {
        'Bytes': 1,
        'KB': 1024,
        'MB': 1024 * 1024,
        'GB': 1024 * 1024 * 1024,
        'TB': 1024 * 1024 * 1024 * 1024
    }
    return usage * units.get(unit, 1)

# Function to format size
def format_size(size_in_bytes):
    suffixes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
    index = 0
    while size_in_bytes >= 1024 and index < len(suffixes) - 1:
        size_in_bytes /= 1024.0
        index += 1
    return f"{size_in_bytes:.2f} {suffixes[index]}"
    
# Function to check if an account has the necessary STS role
def has_sts_role(account_id):
    try:
        sts_client = boto3.client('sts')
        sts_client.assume_role(
            RoleArn=f"arn:aws:iam::{account_id}:role/CrossAccountReadAccess",
            RoleSessionName="check_role_existence"
        )
        return True
    except Exception as e:
        print(f"Account {account_id} does not have the required STS role. Skipping.")
        return

# Function to list distributions for a given AWS account
def list_distributions_for_account(account_id):
    try:
        sts_connection = boto3.client('sts')
        acct_b = sts_connection.assume_role(
            RoleArn=f"arn:aws:iam::{account_id}:role/CrossAccountReadAccess",
            RoleSessionName="cross_acct_lambda"
        )

        ACCESS_KEY = acct_b['Credentials']['AccessKeyId']
        SECRET_KEY = acct_b['Credentials']['SecretAccessKey']
        SESSION_TOKEN = acct_b['Credentials']['SessionToken']

        # create service client using the assumed role credentials, e.g. CloudFront
        client = boto3.client(
            'cloudfront',
            aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY,
            aws_session_token=SESSION_TOKEN,
        )

        response = client.list_distributions()

        dist_list = []
        for i in response['DistributionList']['Items']:
            ele = {
                "DistributionId": i['Id'],
                "DomainName": i['DomainName'],
                "AlternateDomainNames": i.get('Aliases', {}).get('Items', [])
            }
            dist_list.append(ele)

        return dist_list
    except Exception as e:
        print(f"Error listing distributions for account {account_id}: {str(e)}")
        return []

# Function to generate HTML table
def generate_html_table(distributions, distribution_usage, all_days):
    email_body = """
    <html>
    <head>
    <style>
        table {
            border-collapse: collapse;
            width: 100%;
        }
        th, td {
            border: 1px solid black;
            padding: 8px;
            text-align: left;
        }
        th {
            background-color: #F2F2F2;
        }
    </style>
    </head>
    <body>
    <table>
    <tr>
    <th>Distribution ID</th>
    <th>Domain Name</th>
    <th>Alternate Domain Names</th>
    """

    for day in all_days:
        short_day_name = day.strftime('%d')
        email_body += f"<th>{short_day_name}</th>"
    email_body += "<th>Total</th></tr>"

    for dist in distributions:
        distribution_id = dist['DistributionId']
        email_body += f"<tr><td>{distribution_id}</td><td>{dist['DomainName']}</td><td>{', '.join(dist['AlternateDomainNames'])}</td>"
        total_usage_bytes = 0

        for day in all_days:
            usage_data = distribution_usage.get(distribution_id, {})
            usage, unit = usage_data.get(day, (0, "Bytes"))
            usage_in_bytes = convert_usage_to_bytes(usage, unit)
            total_usage_bytes += usage_in_bytes
            formatted_usage = format_size(usage_in_bytes)
            email_body += f'<td>{formatted_usage}</td>'

        formatted_total_usage = format_size(total_usage_bytes)
        email_body += f"<td>{formatted_total_usage}</td></tr>"

        # Debugging print statements to identify potential duplication
        print(f"Distribution ID: {distribution_id}")
        print(f"Total Usage Bytes: {total_usage_bytes}")

    email_body += "</table></body></html>"

    return email_body

def lambda_handler(event, context):
    org_client = boto3.client('organizations')
    org_response = org_client.list_accounts()

    cf_client = boto3.client('cloudfront')
    ce_client = boto3.client('ce', region_name='us-east-1')

    # Set end_date as the current date
    end_date = datetime.utcnow()
    distribution_usage = {}
    
    ac_list = []
    for k in org_response['Accounts']:
        if k.get('Status') == 'ACTIVE' and has_sts_role(k['Id']):
            ac_list.append(k['Id'])

    distributions = []
    for j in ac_list:
        dist_list = list_distributions_for_account(j)
        distributions.extend(dist_list)

    for dist in distributions:
        distribution_id = dist['DistributionId']

        # Set start_date as the first date of the current month
        start_date = end_date.replace(day=1)  # Set day to 1 for the first date of the current month

        # Initialize daily_usage with zeros for all days using defaultdict
        daily_usage = defaultdict(lambda: (0, 'Bytes'))

        response = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['UsageQuantity'],
            GroupBy=[
                {
                    'Type': 'DIMENSION',
                    'Key': 'SERVICE'
                },
            ],
            Filter={
                'And': [
                    {'Dimensions': {'Key': 'SERVICE', 'Values': ['Amazon CloudFront']}},
                    {'Dimensions': {'Key': 'USAGE_TYPE', 'Values': [
                        'AP-DataTransfer-Out-Bytes',
                        'AP-DataTransfer-Out-OBytes',
                        'APS3-DataTransfer-Out-Bytes',
                        'AU-DataTransfer-Out-Bytes',
                        'AU-DataTransfer-Out-OBytes',
                        'CA-DataTransfer-Out-Bytes',
                        'CA-DataTransfer-Out-OBytes',
                        'DataTransfer-Out-Bytes',
                        'EU-DataTransfer-Out-Bytes',
                        'EU-DataTransfer-Out-OBytes',
                        'IN-DataTransfer-Out-Bytes',
                        'IN-DataTransfer-Out-OBytes',
                        'JP-DataTransfer-Out-Bytes',
                        'JP-DataTransfer-Out-OBytes',
                        'ME-DataTransfer-Out-Bytes',
                        'ME-DataTransfer-Out-OBytes',
                        'SA-DataTransfer-Out-Bytes',
                        'SA-DataTransfer-Out-OBytes',
                        'US-DataTransfer-Out-Bytes',
                        'US-DataTransfer-Out-OBytes',
                        'USE2-DataTransfer-Out-OBytes',
                        'ZA-DataTransfer-Out-Bytes',
                        'ZA-DataTransfer-Out-OBytes'
                    ]}},
                ]
            }
        )
    
        for result_by_time in response['ResultsByTime']:
            start = datetime.strptime(result_by_time['TimePeriod']['Start'], '%Y-%m-%d').date()
            usage = float(result_by_time['Groups'][0]['Metrics']['UsageQuantity']['Amount'])
            unit = result_by_time['Groups'][0]['Metrics']['UsageQuantity']['Unit']
    
            # Update daily_usage for the specific day
            daily_usage[start] = (daily_usage[start][0] + usage, unit)
    
            # Print fetched usage for each distribution after processing
            print(f"Distribution ID: {distribution_id}, Date: {start}, Usage: {usage} {unit}")
    
        distribution_usage[distribution_id] = daily_usage  # Store usage data for each distribution separately
    
    all_days = sorted(set(day for usage_data in distribution_usage.values() for day in usage_data.keys()))

    email_body = generate_html_table(distributions, distribution_usage, all_days)

    current_month = start_date.strftime('%B')
    current_year = start_date.strftime('%Y')

    # Create email content
    body_html = f'<html><body><h4>CloudFront MTD Report <br> {current_month} {current_year}</h4>{email_body}</body></html>'

    sender = 'ashutosh.deshmukh@whistlemind.com'
    recipient = 'ashutosh.deshmukh@whistlemind.com'

    subject = f'CloudFront MTD Usage Report - {current_year}'
    send_email(subject, body_html, sender, recipient)

    return {
        'statusCode': 200,
        'body': 'Function executed successfully'
    }

