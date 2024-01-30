import boto3
from datetime import datetime, timedelta

def get_YTM_dates():
    today = datetime.now()
    start_date = datetime(today.year, 1, 1)
    end_date = today.replace(day=(today.replace(month=12) - timedelta(days=today.day)).day)
    return start_date, end_date

def get_cost_and_usage(start_date, end_date):
    client = boto3.client('ce', region_name='us-east-1')

    response = client.get_cost_and_usage(
        TimePeriod={
            'Start': start_date.strftime('%Y-%m-%d'),
            'End': end_date.strftime('%Y-%m-%d')
        },
        Granularity='MONTHLY',
        Metrics=['BlendedCost'],
        GroupBy=[
            {'Type': 'DIMENSION', 'Key': 'LINKED_ACCOUNT'}
        ],
        Filter={
            "Not": {
                'Dimensions': {
                    'Key': 'RECORD_TYPE',
                    'Values': ['Credit', 'Refund']
                }
            }
        }
    )

    data = []

    for i in response['ResultsByTime']:
        date = i['TimePeriod']['Start']

        for j in i['Groups']:
            account_id = j['Keys'][0]
            amount = j['Metrics']['BlendedCost']['Amount']
            currency = j['Metrics']['BlendedCost']['Unit']
            for j in response['DimensionValueAttributes']:
                if account_id == j['Value']:
                    account_name = j['Attributes']['description']
            data.append({'Date': date,'Account ID': account_id, 'Account Name': account_name, 'Amount': amount, 'Currency': currency})

    return data

def format_data_to_html(data, float_format='%.2f'):
    html_table = "<table style='border-collapse: collapse; width: 100%; border: 1px solid black;'><tr><th style='border: 1px solid black; text-align: center; background-color: #F2F2F2;'>Account ID</th><th style='border: 1px solid black; text-align: center; background-color: #F2F2F2;'>Account Name</th>"

    # Extract unique dates
    dates = sorted(set(item['Date'] for item in data))

    for date in dates:
        month_name = datetime.strptime(date, '%Y-%m-%d').strftime('%b')
        html_table += f"<th style='border: 1px solid black; text-align: center; background-color: #F2F2F2;'>{month_name}</th>"

    # Add Total column header
    html_table += "<th style='border: 1px solid black; font-weight: bold; text-align: center; background-color: #F2F2F2;'>Total</th></tr>"

    account_ids = sorted(set(item['Account ID'] for item in data))

    for account_id in account_ids:
        account_data = [item for item in data if item['Account ID'] == account_id]
        account_name = account_data[0]['Account Name'] if account_data else '-'
        html_table += f"<tr><td style='border: 1px solid black; text-align: center;'>{account_id}</td><td style='border: 1px solid black; text-align: left;'>{account_name}</td>"

        total_cost = 0  # Initialize total cost for the account

        for date in dates:
            cost = next((item['Amount'] for item in account_data if item['Date'] == date), '-')
            if cost != '-':
                cost = round(float(cost), 2)  # Convert the cost to a floating-point number
                formatted_cost = float_format % cost
                html_table += f"<td style='border: 1px solid black; text-align: center;'>{formatted_cost}</td>"

                total_cost += cost  # Accumulate cost for the total column
            else:
                html_table += f"<td style='border: 1px solid black; text-align: center;'>{cost}</td>"

        # Add Total column value
        total_formatted_cost = float_format % total_cost
        html_table += f"<td style='border: 1px solid black; font-weight: bold; text-align: center; background-color: #F2F2F2;'>{total_formatted_cost}</td>"

        html_table += "</tr>"

    html_table += "</table>"

    return html_table


def lambda_handler(event, context):
    # Retrieve Year-to-Date (YTM) dates
    start_date, end_date = get_YTM_dates()

    # Retrieve AWS cost and usage data
    cost_data = get_cost_and_usage(start_date, end_date)

    # Format data as HTML table with account ID and date
    html_table = format_data_to_html(cost_data, float_format='%.2f')

    # Get AWS Account ID
    sts_client = boto3.client('sts')
    account_id = sts_client.get_caller_identity()['Account']

    # Configure SES
    ses = boto3.client('ses', region_name='us-east-1')
    sender_email = 'ashutosh.deshmukh@whistlemind.com'
    recipient_email = 'ashutosh.deshmukh@whistlemind.com'

    # Get current year and month (3-letter name)
    current_year = start_date.strftime('%Y')
    current_month = start_date.strftime('%b')[:3]  # Use only three letters of the month

    # Create email subject with current year and month, and AWS Account ID
    subject = f'YTM Report for Linked Account - {account_id} {current_month} {current_year}'

    # Create email content
    body_html = f'<html><body><h4>YTM Report for Linked Account - {account_id} <br> Year {current_year} </h4> <h5>Currency: {cost_data[0]["Currency"]}</h5>{html_table}</body></html>'

    # Send email
    response = ses.send_email(
        Source=sender_email,
        Destination={'ToAddresses': [recipient_email]},
        Message={
            'Subject': {'Data': subject},
            'Body': {'Html': {'Data': body_html}}
        }
    )

    return {
        'statusCode': 200,
        'body': 'Email sent successfully'
    }
