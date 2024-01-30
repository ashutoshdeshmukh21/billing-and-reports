import boto3
from datetime import datetime

def get_mtd_dates():
    today = datetime.now()
    start_date = datetime(today.year, today.month, 1)
    end_date = today
    return start_date, end_date

def get_cost_and_usage(start_date, end_date):
    client = boto3.client('ce', region_name='us-east-1')

    response = client.get_cost_and_usage(
        TimePeriod={
            'Start': start_date.strftime('%Y-%m-%d'),
            'End': end_date.strftime('%Y-%m-%d')
        },
        Granularity='DAILY',
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
            data.append({'Date': date, 'Account ID': account_id, 'Account Name': account_name, 'Amount': amount,
                         'Currency': currency})

    return data

def format_data_to_html(data, float_format='%.2f'):
    html_table = "<table style='border-collapse: collapse; width: 100%; border: 1px solid black;'><tr><th style='border: 1px solid black; text-align: le; background-color: #F2F2F2;'>Account ID</th><th style='border: 1px solid black; text-align: left; background-color: #F2F2F2;'>Account Name</th>"

    # Extract unique dates
    dates = sorted(set(item['Date'] for item in data))

    for date in dates:
        day_only = datetime.strptime(date, '%Y-%m-%d').strftime('%d')
        html_table += f"<th style='border: 1px solid black; text-align: center; background-color: #F2F2F2;'>{day_only}</th>"

    # Add Total column header
    html_table += "<th style='border: 1px solid black; font-weight: bold; text-align: center; background-color: #F2F2F2;'>Total</th></tr>"

    account_ids = sorted(set(item['Account ID'] for item in data))

    for account_id in account_ids:
        account_data = [item for item in data if item['Account ID'] == account_id]
        account_name = account_data[0]['Account Name'] if account_data else 'N/A'
        html_table += f"<tr><td style='border: 1px solid black; text-align: center;'>{account_id}</td><td style='border: 1px solid black; text-align: left;'>{account_name}</td>"

        total_cost = 0  # Initialize total cost for the account

        for date in dates:
            cost = next((item['Amount'] for item in account_data if item['Date'] == date), 'N/A')
            if cost != 'N/A':
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
    # Retrieve Month-to-Date (MTD) dates
    start_date, end_date = get_mtd_dates()

    # Retrieve AWS cost and usage data
    cost_data = get_cost_and_usage(start_date, end_date)

    # Format data as HTML table with account ID and date
    html_table = format_data_to_html(cost_data, float_format='%.2f')

    # Extract the currency from the first item in the cost_data list
    currency = cost_data[0]['Currency'] if cost_data else 'N/A'

    # Get AWS Account ID
    sts_client = boto3.client('sts')
    account_id = sts_client.get_caller_identity()['Account']

    # Configure SES
    ses = boto3.client('ses', region_name='us-east-1')
    sender_email = 'ashutosh.deshmukh@whistlemind.com'
    recipient_email = 'ashutosh.deshmukh@whistlemind.com'

    # Get current month and year
    current_month = start_date.strftime('%B')
    current_year = start_date.strftime('%Y')

    # Create email subject with current month, year, and AWS Account ID, including start and end dates
    subject = f'MTD Report for Linked Account - {account_id} {current_month} {current_year}'

    # Create email content
    body_html = f"<html><body><h4>MTD Report for Linked Account - {account_id} <br> {current_month} {current_year} </h4><h5>Currency: {currency}</h5><p>{html_table}</p></body></html>"

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
