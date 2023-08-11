import boto3
import random


high_scheduler_arn = "arn:aws:events:us-east-1:000000000000:rule/mykms-high-scheduler"
low_scheduler_arn = "arn:aws:events:us-east-1:000000000000:rule/mykms-low-scheduler"
high_response_alarm_arn = "arn:aws:cloudwatch:us-east-1:000000000000:alarm:mykms-response-high-sign"
low_response_alarm_arn = "arn:aws:cloudwatch:us-east-1:000000000000:alarm:mykms-response-low-sign"
main_hsms = ["hsm-000000000000"]
cluster_id = 'cluster-000000000000'
availability_zones = ['us-east-1b']
OK_TO_ALARM = 0
ALARM_TO_OK = 1
MIN_HSM_NUMBER = 1
MAX_HSM_NUMBER = 6
DEBUG = True


cloudhsm = boto3.client("cloudhsmv2", region_name="us-east-1")
eventbridge = boto3.client('events', region_name="us-east-1")
cloudwatch = boto3.client('cloudwatch', region_name="us-east-1")

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)
    
    

def state_change(detail, alarm_type):
    current = detail["state"]["value"]
    previous = detail["previousState"]["value"]
    if alarm_type == "high":
        if previous == 'ALARM' and current in ['OK', 'INSUFFICIENT_DATA']:
            return ALARM_TO_OK
        elif previous in ['OK', 'INSUFFICIENT_DATA'] and current == 'ALARM':
            return OK_TO_ALARM
        else:
            return
    else:
        if previous in ['ALARM', 'INSUFFICIENT_DATA'] and current == 'OK':
            return ALARM_TO_OK
        elif previous == 'OK' and current in ['ALARM', 'INSUFFICIENT_DATA']:
            return OK_TO_ALARM
        else:
            return
    

def get_hsm():
    return cloudhsm.describe_clusters(
        Filters={'clusterIds': [cluster_id]}
        )['Clusters'][0]['Hsms']
    

def get_running_hsm():
    hsms = get_hsm()
    return [hsm for hsm in hsms if hsm["State"]=='ACTIVE']
    
    
def get_removable_hsm():
    return [hsm['HsmId'] for hsm in get_running_hsm() if hsm['HsmId'] not in main_hsms]
    
    
def remove_hsm():
    hsms = get_running_hsm()
    if len(hsms) <= MIN_HSM_NUMBER:
        debug_print("min running hsm number reached, will not remove hsm.")
        return
    else:
        available_hsm_ids = get_removable_hsm()
        debug_print(f"randomly remove 1 HSM node")
        res = cloudhsm.delete_hsm(ClusterId=cluster_id, HsmId=random.choice(available_hsm_ids))
        debug_print(f'Removed HsmId: {res["HsmId"]}')
 

def add_hsm():
    hsms = get_hsm()
    if len(hsms) >= MAX_HSM_NUMBER:
        debug_print("Max hsm number reached, will not add hsm.")
        return
    else:
        debug_print("increase 1 HSM node")
        res = cloudhsm.create_hsm(ClusterId=cluster_id, AvailabilityZone=random.choice(availability_zones))
        debug_print(f'HsmId: {res["Hsm"]["HsmId"]}')

def get_rule_name(rule_arn):
    return rule_arn.split('/')[1]
    
    
def disable_rule(rule_arn):
    debug_print("rulename: "+ get_rule_name(rule_arn))
    return eventbridge.disable_rule(Name=get_rule_name(rule_arn))


def enable_rule(rule_arn):
    debug_print("rulename: "+ get_rule_name(rule_arn))
    return eventbridge.enable_rule(Name=get_rule_name(rule_arn))


def in_alarm_state(alarm_arn):
    alarm_name = alarm_arn.split(':')[-1]
    response = cloudwatch.describe_alarms(AlarmNames=[alarm_name])
    debug_print(f"alarm name: {alarm_name}, alarm_state: {response['MetricAlarms'][0]['StateValue']}")
    if response['MetricAlarms'][0]['StateValue'] == 'ALARM':
        return True
    if response['MetricAlarms'][0]['StateValue'] == 'INSUFFICIENT_DATA' and 'mykms-response-low' in alarm_name:
        return True
    

def lambda_handler(event, context):
    trigger = event["resources"][0]
    detail = event["detail"]
        
    if trigger == high_scheduler_arn:
        if in_alarm_state(high_response_alarm_arn):
            debug_print("receive high_scheduler event")
            running_hsms_number = len(get_running_hsm())
            if running_hsms_number >= MAX_HSM_NUMBER:
                debug_print("disable high_scheduler due to max hsm limit")
                disable_rule(high_scheduler_arn)
                return
            else:
                debug_print("try to add one more hsm due to high scheduler event")
                add_hsm()
                return
        else:
            debug_print("high_scheduler event with high_alarm_OK status, \
            this may be caused by initial setup, ignore, wait until the scaling \
            state stable.")
            return
    elif trigger == low_scheduler_arn:
        if in_alarm_state(low_response_alarm_arn):
            debug_print("receive low_scheduler event")
            hsms_number = len(get_hsm())
            if hsms_number <= MIN_HSM_NUMBER:
                debug_print("disable low_scheduler due to min hsm limit")
                disable_rule(low_scheduler_arn)
                return
            else:
                debug_print("try to remove one hsm due to low scheduler event")
                remove_hsm()
                return
        else:
            debug_print("low_scheduler event with low_alarm_OK status, \
            this may be caused by initial setup, ignore, wait until the scaling \
            state stable.")
            return
    elif trigger == high_response_alarm_arn:
        if state_change(detail, "high") == OK_TO_ALARM:
            debug_print("high response alarm from OK to ALARM")
            debug_print("enable high_scheduler rule")
            enable_rule(high_scheduler_arn)
            debug_print("disable low_scheduler rule")
            disable_rule(low_scheduler_arn)
            return
        elif state_change(detail, "high") == ALARM_TO_OK:
            debug_print("high response alarm from ALARM to OK")
            debug_print("disable high scheduler rule")
            disable_rule(high_scheduler_arn)
            return
        else:
            print(f'IgnoredStateChange, {detail["previousState"]["value"]} -> {detail["state"]["value"]}')
            return
    elif trigger == low_response_alarm_arn:
        if state_change(detail, "low") == OK_TO_ALARM:
            debug_print("low response alarm from OK to ALARM")
            debug_print("enable low_scheduler rule")
            enable_rule(low_scheduler_arn)
            disable_rule(high_scheduler_arn)
            return
        elif state_change(detail, "low") == ALARM_TO_OK:
            debug_print("low response alarm from ALARM to OK")
            debug_print("disable low_scheduler rule")
            disable_rule(low_scheduler_arn)
            return
        else:
            print(f'IgnoredStateChange, {detail["previousState"]["value"]} -> {detail["state"]["value"]}')
            return
    else:
        raise Exception("UnknownTrigger")
    
    
    