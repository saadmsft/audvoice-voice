using 'main.bicep'

param rgName = 'rg-audvoice'
param location = 'uaenorth'
param namePrefix = 'audvoice'
param containerImage = '' // set to '<acr>.azurecr.io/audvoice:latest' after first push
param jwtSecret = readEnvironmentVariable('AUDVOICE_JWT_SECRET', '')
param apiKeysCsv = readEnvironmentVariable('AUDVOICE_API_KEYS', '')
