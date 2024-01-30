import boto3
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import calendar

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
            {'Type': 'DIMENSION', 'Key': 'SERVICE'}
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
            service = j['Keys'][0]
            amount = j['Metrics']['BlendedCost']['Amount']
            currency = j['Metrics']['BlendedCost']['Unit']
            data.append({'Date': date, 'Service': service, 'Amount': amount, 'Currency': currency})

    return data

def lambda_handler(event, context):
    # Retrieve Month-to-Date (MTD) dates
    start_date, end_date = get_mtd_dates()
    
    # Retrieve AWS cost and usage data
    cost_data = get_cost_and_usage(start_date, end_date)
    
    # Format data as HTML table with service and date
    html_table = "<table border='1'><tr><th>Service</th>"

    # Extract unique dates
    dates = sorted(set(item['Date'] for item in cost_data))

    # Initialize column-wise total dictionary
    column_totals = {date: 0.0 for date in dates}

    for date in dates:
        # Extract day from the date
        day = datetime.strptime(date, '%Y-%m-%d').day
        html_table += f"<th>{day}</th>"

    html_table += "<th><b>Total</b></th></tr>"

    services = sorted(set(item['Service'] for item in cost_data))

    for service in services:
        service_data = [item for item in cost_data if item['Service'] == service]
        html_table += f"<tr><td>{service}</td>"

        row_total = 0.0

        for date in dates:
            cost = next((item['Amount'] for item in service_data if item['Date'] == date), '-')
            if cost != '-':
                cost = float(cost)  # Convert the cost to a floating-point number
                formatted_cost = f"{cost:.2f}"  # Include currency
                if date == 'Total':
                    html_table += f"<td style='text-align: center;'><b>{formatted_cost}</b></td>"
                else:
                    html_table += f"<td style='text-align: center;'>{formatted_cost}</td>"
                column_totals[date] += cost
                row_total += cost
            else:
                html_table += f"<td>{cost}</td>"

        formatted_row_total = f"{row_total:.2f}"  # Include currency
        html_table += f"<td style='text-align: center;'><b>{formatted_row_total}</b></td></tr>"

    html_table += "<tr><td><b>Total</b></td>"

    # Calculate and display column-wise total
    grand_total = 0.0
    for date in dates:
        column_total = column_totals[date]
        formatted_column_total = f"{column_total:.2f}"  # Include currency
        html_table += f"<td style='text-align: center;'><b>{formatted_column_total}</b></td>"
        grand_total += column_total

    formatted_grand_total = f"{grand_total:.2f}"  # Include currency
    html_table += f"<td style='text-align: center;'><b>{formatted_grand_total}</b></td></tr></table>"
    
    # Use the HTML logic from the first code to generate the email body
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
    """ + html_table + """
    </body></html>
    """

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
    subject = f'MTD Cost Report by Service - {account_id}  {current_month} {current_year}'
    
    # Create email content
    body_html = f'<html><body><h4>MTD Cost Report by Account Services - {account_id} <br> {current_month} {current_year}</h4> <h5> Currency: {service_data[0]["Currency"]}</h5>{email_body}</body></html>'
    
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
