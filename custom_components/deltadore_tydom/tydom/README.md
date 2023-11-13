# How is Tydom working ?

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
this is also available using websockets.

connection to Tydom/cloud mediation server
GET request to https://host:443/mediation/client?mac=001Axxxxxxxx&appli=1
host is either tydom ip or mediation server address (depending on mode used)
This first request is used to get the digest authentication informations and to indicate the server that we want to upgrade connection to websockets using request headers

GET request to wss://host:443/mediation/client?mac=001Axxxxxxxx&appli=1
this request is sent with digest authentication challenge answer

We now have a websocket connection to send commands

Init flow used by the app :
GET /ping
GET /info
PUT /configs/gateway/api_mode
GET /configs/gateway/geoloc
GET /configs/gateway/local_claim
GET /devices/meta
GET /areas/meta
GET /devices/cmeta
GET /areas/cmeta
GET /devices/data
GET /areas/data
POST /refresh/all
