# coding=utf-8
##########################################################################################
# Name: PIA_Policy_Bot
# Description:
# This is a monitoring script for cataloged data sources schemas.  It
# checks if a schema fits a combination of conditions which require a privacy impact assessment.
# The rules are all three of the following must be true:
#  - Geographic location of data is European Union of United States
#  - Security classification is confidential
#  - Lifecycle stage is Production
#
# If the conditions are found then it triggers a notification to the steward assigned
# to the data source via a conversation.  It also checks if there is a
# previous conversation already generated for the same reason which has
# not been resolved, as we don't want to overwhelm the steward with
# duplicative notices.
#
# The code uses the Alation Django framework.
#
# Author: Alation
# Alation Catalog Version: 2021.3
#
# Catalog Requirements:
# 1. Custom Field of type Picker named Security Classification
# 2. Custom Field of type Picker named Lifecycle Stage
# 3. Custom Field of type Picker named Geographic Location
#
# Notice of Usage, Rights, and Alation Responsibility:
# This code is provided as an example and is not intended for use on production
# Alation Catalog instances.  It should only be used on non-production Alation
# catalog instances.  Alation does not provide support for the code and it is not
# covered by the Alation subscription and its associated support agreement. Alation
# is not responsible for any harm it may cause, including the unrecoverable corruption
# of a catalog instance. Its recommended that modifications to this code and production
# use by Alation customers only be done with the direct engagement of Alation
# Professional Services.
#
##########################################################################################

import bootstrap_rosemeta
from django.db.models import Count
from rosemeta.models import cast_to_uuid
from rosemeta.models import GroupProfile
from rosemeta.models.models_text import Article
from rosemeta.models.models_customize import CustomField, CustomFieldValue, CustomGlossary, CustomTemplate
from logical_metadata.models.models_values import PickerFieldValue
from alation_object_type_directory.resources import ObjectKey
from alation_object_type_directory.resources import cast_to_uuid
from alation_object_types.enums import ObjectType
from logical_metadata.models import Operation
from logical_metadata.public.builtin_field_helpers import update_assignee
from rosemeta.models import DataSource, Schema
from rosemeta.models import Post
from rosemeta.models import PostType
from rosemeta.models import Thread
from stewardship.models import UserTask
from stewardship.enums import UserTaskType
from rosemeta.models.enums import CustomFieldType
from logical_metadata.resources import *
from django.contrib.auth.models import Group
from django.contrib.auth.models import User
import urllib
from datetime import datetime, timedelta, timezone

# get the server admins and catalog admins in case we need to assign them to a conversatio
server_admins = GroupProfile.objects.get(group__name="Server Admins").group
my_admin = server_admins.user_set.first()
catalog_admins = GroupProfile.objects.get(group__name="Catalog Admins").group
policyBot = User.objects.get(username='jdubudubu@gmail.com')

# defaults for generated conversations
title='Action Required: Privacy Impact Assessment Needed'
text='This schema is classified as Compliance, Production, and in the United Stated.' \
    ' Policy requires this combination to have a Privacy Impact Assessment every six ' \
    'months. Mark the task resolved when completed. '

# check data sources and finding stewards so a message can be trigger to them
d = Schema.objects.all().values('id','ts_created')
for k in d:

    # declare variables
    steward = 'None'
    found = False
    security = ''
    geo = ''
    lifecycle = ''
    stewardid = 0

    # get all picker fields
    v=PickerFieldValue.objects.filter(otype=ObjectType.SCHEMA).values()

    # iterate over the picker fields looking for our fields
    for i in v:

        # get the steward on the data source in case we need to know them later - 8 is the field_id for Stewards
        if i['oid']==cast_to_uuid(k['id']) and i['field_id'] == 8:

            # get the first in what could be a list of stewards
            first = i['object_set'][0]

            # the value is a combination of type (user or group) and id so we split these
            type,id=first.split("_")

            # user
            if type == '33':
                steward = User.objects.filter(id=id).values('id','username')
                #print('steward:' + steward[0]['username'])
                #print('steward ID:' + str(steward[0]['id']))
                stewardid = steward[0]['id']

            # group
            if type == '38':
                steward = GroupProfile.objects.filter(id=id).values('builtin_name')

        # look for Security Class
        if i['field_id'] == 10008 and i['oid']==cast_to_uuid(k['id']):
            security = i['object_set'][0]
            #print('Security: ' + security)

        # look for Geo
        if i['field_id'] == 10030 and i['oid']==cast_to_uuid(k['id']):
            geo = i['object_set'][0]
            #print('geo: ' + geo)

        #  look for lifecycle
        if i['field_id'] == 10031 and i['oid']==cast_to_uuid(k['id']):
            lifecycle = i['object_set'][0]
            #print('lifecycle: ' + lifecycle)

    # if all conditions are true on the same schema then trigger a workflow
    if security == 'Compliance' and (geo == 'United States' or geo == 'European Union') and lifecycle == 'Production':
        found = True

        # declare variables
        task_exist_or_approved = False

        # check if a conversation already exists and it is not approved yet, so we don't repeat - task_status=0 is
        # not approved
        for my_thread in Thread.objects.filter(_subject_oid=cast_to_uuid(k['id']), subject_otype='schema').values():
            my_user_task = UserTask.objects.filter(subject_otype=ObjectType.THREAD, subject_uuid=cast_to_uuid(my_thread.get('id')), task_status=0, deleted=False)
            mut_len = len(my_user_task)
            
            # task exists but not approved
            if mut_len==1 and my_thread['title'] == title:
                task_exist_or_approved = True

        # check if conversation already exists and is approved - unlikely unless the check happens infrequently
        for my_thread in Thread.objects.filter(_subject_oid=cast_to_uuid(k['id']), subject_otype='schema').values():
            my_user_task = UserTask.objects.filter(subject_otype=ObjectType.THREAD, subject_uuid=cast_to_uuid(my_thread.get('id')), task_status=1, deleted=False)
            mut_len = len(my_user_task)

            if mut_len==1 and my_thread['title'] == title:
                task_exist_or_approved = True

        # if conversation existence check failed then create the new conversation
        if task_exist_or_approved == False:

            # create a discussion thread using the text argument, but replacing title and template
            question=dict(otype='post', post_type='question', text=text.format(title=title))

            # create the conversation (aka a thread)
            thread = Thread.objects.create(author=policyBot, _subject_oid=cast_to_uuid(k['id']), subject_otype='schema', title=title, question_post=question)

            # get the user as found above when processing the data source, if no steward assign to server admin
            if stewardid == 0:
                uid = my_admin.id
            else:
                uid = stewardid

            # get the task object key so we can update the assigned
            user_task_obj_key = ObjectKey(ObjectType.USER_TASK, thread.user_task_id())
            update_assignee(user_task_obj_key, ObjectKey(ObjectType.USER, uid), Operation.ADD, policyBot.id)
