#!/bin/bash

# Basic build command for Arma with VN

docker build -f ./dockerfiles/arma/Dockerfile -t savagegamedesign/arma:2.20 --secret id=STEAM_USERNAME,src=./secrets/steam_username --secret id=STEAM_PASSWORD,src=./secrets/steam_password --build-arg CDLCS=vn .