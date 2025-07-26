import requests
from token_manager import get_valid_upstox_access_token

def main():
    access_token = get_valid_upstox_access_token()

    # Define the endpoint for bulk quotes
    url = 'https://api.upstox.com/v2/market-quote/quotes?instrument_key=NSE_EQ%7CINE848E01016,NSE_EQ|INE669E01016'

    # Define the headers including the access token
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    # Make the GET request to the API
    response = requests.get(url, headers=headers)

    # Print the response
    print("Status Code:", response.status_code)
    print("Response JSON:", response.json())

main()



