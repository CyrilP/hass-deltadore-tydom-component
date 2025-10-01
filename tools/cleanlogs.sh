#!/bin/bash

#cat $1 | grep "Incomming message" | sed "s/.*b'//g" 
cat $1 | grep "Incoming message" | sed "s/.*b'//g" | sed "s/'$//g" |sed "s/\\\\x[a-f0-9][a-f0-9]/X/g" | sed "s/\\\\'/'/g"
