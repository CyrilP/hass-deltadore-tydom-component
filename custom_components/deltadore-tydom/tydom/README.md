# How it Tydom working ?

## Authentication
GET request to https://deltadoreadb2ciot.b2clogin.com/deltadoreadb2ciot.onmicrosoft.com/v2.0/.well-known/openid-configuration?p=B2C_1_AccountProviderROPC_SignIn

It gives the authorization endpoint and what's supported. we retrieve the token endpoint URL from there : https://deltadoreadb2ciot.b2clogin.com/deltadoreadb2ciot.onmicrosoft.com/oauth2/v2.0/token?p=b2c_1_accountproviderropc_signin

POST request to the token endpoint with :
Content-Type header = multipart form data encoded credentials, grant type, client_id and scope :
{
    "username": "email",
    "password": "password",
    "grant_type": DELTADORE_AUTH_GRANT_TYPE,
    "client_id": DELTADORE_AUTH_CLIENTID,
    "scope": DELTADORE_AUTH_SCOPE
}

we retrieve the access_token from the response
we can now query the Delta Dore API using the bearer token

get the tydom password:
https://prod.iotdeltadore.com/sitesmanagement/api/v1/sites?gateway_mac=xxx

{"count":1,"sites":[{"id":"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx","creation_date":"2022-09-06T11:39:51.19+02:00","gateway":{"id":"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx","creation_date":"22022-09-06T11:39:51.19+02:00","hashes":[],"mac":"001Axxxxxxxx","password":"xxxx"},"cameras":[]}]}

Get the list of devices, endpoints, attributes, services :
POST request to https://pilotage.iotdeltadore.com/pilotageservice/api/v1/control/gateways
{
  "id": "001Axxxxxxxx"
}

The id is the mac address


