import pdfkit
import boto3
from datetime import datetime, timedelta
from collections import defaultdict

def convert_usage_to_bytes(usage, unit):
    units = {
        'Bytes': 1,
        'KB': 1024,
        'MB': 1024 * 1024,
        'GB': 1024 * 1024 * 1024,
        'TB': 1024 * 1024 * 1024 * 1024
    }
    return usage * units.get(unit, 1)

def format_size(size_in_bytes):
    suffixes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
    index = 0
    while size_in_bytes >= 1024 and index < len(suffixes) - 1:
        size_in_bytes /= 1024.0
        index += 1
    return f"{size_in_bytes:.2f} {suffixes[index]}"

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
        email_body += f"<tr><td>{distribution_id}</td><td>{dist['DomainName']}</td><td>{', '.join(dist['ulternateDomainNames'])}</td>"
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

    email_body += "</table></body></html>"

    return email_body

def generate_pdf_report(distributions, distribution_usage, all_days):
    pdf_options = {
        'page-size': 'A4',
        'margin-top': '10mm',
        'margin-right': '10mm',
        'margin-bottom': '10mm',
        'margin-left': '10mm'
    }

    pdf_filename = '/home/ashutosh/Documents/cloudfront_report.pdf'

    pdfkit.from_string(generate_html_table(distributions, distribution_usage, all_days), pdf_filename, options=pdf_options)

    return pdf_filename

def lambda_handler(event, context):
    org_client = boto3.client('organizations')
    org_response = org_client.list_accounts()

    distributions = []
    distribution_usage = {}

    ac_list = []
    for k in org_response['Accounts']:
        if k.get('Status') == 'ACTIVE':
            dist_list = list_distributions_for_account(k['Id'])
            distributions.extend(dist_list)

    for dist in distributions:
        distribution_id = dist['DistributionId']

        start_date = datetime.utcnow().replace(day=1)

        daily_usage = defaultdict(lambda: (0, 'Bytes'))

        response = None  # Mock response, replace with actual data retrieval logic

        for result_by_time in response['ResultsByTime']:
            start = datetime.strptime(result_by_time['TimePeriod']['Start'], '%Y-%m-%d').date()
            usage = float(result_by_time['Groups'][0]['Metrics']['UsageQuantity']['Amount'])
            unit = result_by_time['Groups'][0]['Metrics']['UsageQuantity']['Unit']

            daily_usage[start] = (daily_usage[start][0] + usage, unit)

        distribution_usage[distribution_id] = daily_usage

    all_days = sorted(set(day for usage_data in distribution_usage.values() for day in usage_data.keys()))

    pdf_filename = generate_pdf_report(distributions, distribution_usage, all_days)

    return {
        'statusCode': 200,
        'body': 'PDF report generated successfully',
        'pdf_filename': pdf_filename
    }
