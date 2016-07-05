# -*- coding: utf-8 -*-
# Copyright (C) 2014-2016 Andrey Antukh <niwi@niwi.nz>
# Copyright (C) 2014-2016 Jesús Espino <jespinog@gmail.com>
# Copyright (C) 2014-2016 David Barragán <bameda@dbarragan.com>
# Copyright (C) 2014-2016 Alejandro Alonso <alejandro.alonso@kaleidos.net>
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re
import os

from django.utils.translation import ugettext as _

from taiga.projects.issues.models import Issue
from taiga.projects.tasks.models import Task
from taiga.projects.userstories.models import UserStory
from taiga.projects.history.services import take_snapshot
from taiga.projects.notifications.services import send_notifications
from taiga.hooks.event_hooks import BaseEventHook
from taiga.hooks.exceptions import ActionSyntaxException

from .services import get_gitlab_user


class GitLabEventHook(BaseEventHook):
    platform = "GitLab"
    platform_prefix = "gl"

    def replace_gitlab_references(self, project_url, wiki_text):
        if wiki_text is None:
            wiki_text = ""

        template = "\g<1>[GitLab#\g<2>]({}/issues/\g<2>)\g<3>".format(project_url)
        return re.sub(r"(\s|^)#(\d+)(\s|$)", template, wiki_text, 0, re.M)


class PushEventHook(GitLabEventHook):
    def process_event(self):
        if self.payload is None:
            return

        commits = self.payload.get("commits", [])
        for commit in commits:
            self._process_message(commit, None)

    def _process_message(self, commit, gitlab_user):
        """
          The message we will be looking for seems like
            TG-XX #yyyyyy
          Where:
            XX: is the ref for us, issue or task
            yyyyyy: is the status slug we are setting
        """
        message = commit.get("message", None)
        if message is None:
            return

        p = re.compile("tg-(\d+) +#([-\w]+)")
        for m in p.finditer(message.lower()):
            ref = m.group(1)
            status_slug = m.group(2)
            self._change_status(ref, status_slug, gitlab_user, commit)

    def _change_status(self, ref, status_slug, gitlab_user, commit):
        element = self.set_item_status(ref, status_slug)

        project_url = self.payload.get('repository', {}).get('homepage', None)

        gitlab_user_name = commit.get('author', {}).get('name', None)
        gitlab_user_url = None
        if project_url and gitlab_user_name:
            gitlab_user_url = os.path.join(os.path.dirname(os.path.dirname(project_url)), "u", gitlab_user_name)

        commit_id = commit.get("id", None)
        commit_url = commit.get("url", None)
        commit_message = commit.get("message", None)

        comment = self.generate_status_change_comment(
            user_name=gitlab_user_name,
            user_url=gitlab_user_url,
            commit_id=commit_id[:7],
            commit_url=commit_url,
            commit_message=commit_message
        )

        snapshot = take_snapshot(element, comment=comment,
                                 user=get_gitlab_user(gitlab_user))
        send_notifications(element, history=snapshot)


class IssuesEventHook(GitLabEventHook):
    def process_event(self):
        if self.payload.get('object_attributes', {}).get("action", "") != "open":
            return

        number = self.payload.get('issue', {}).get('iid', None)
        subject = self.payload.get('object_attributes', {}).get('title', None)
        description = self.payload.get('object_attributes', {}).get('description', None)
        gitlab_reference = self.payload.get('object_attributes', {}).get('url', None)

        project_url = self.payload.get('repository', {}).get('homepage', None)

        gitlab_url = os.path.join(project_url, "issues", str(number))
        gitlab_user_name = self.payload.get('user', {}).get('username', None)
        gitlab_user_url = os.path.join(os.path.dirname(os.path.dirname(project_url)), "u", gitlab_user_name)

        project_url = None
        if gitlab_reference:
            project_url = os.path.basename(os.path.basename(gitlab_reference))

        if not all([subject, gitlab_reference, project_url]):
            raise ActionSyntaxException(_("Invalid issue information"))

        issue = Issue.objects.create(
            project=self.project,
            subject=subject,
            description=self.replace_gitlab_references(project_url, description),
            status=self.project.default_issue_status,
            type=self.project.default_issue_type,
            severity=self.project.default_severity,
            priority=self.project.default_priority,
            external_reference=['gitlab', gitlab_reference],
            owner=get_gitlab_user(None)
        )
        take_snapshot(issue, user=get_gitlab_user(None))

        comment = self.generate_new_issue_comment(
            user_name=gitlab_user_name,
            user_url=gitlab_user_url,
            number=number,
            subject=subject,
            platform_url=gitlab_url,
            description=description
        )

        snapshot = take_snapshot(issue, comment=comment, user=get_gitlab_user(None))
        send_notifications(issue, history=snapshot)


class IssueCommentEventHook(GitLabEventHook):
    def process_event(self):
        if self.payload.get('object_attributes', {}).get("noteable_type", None) != "Issue":
            return

        number = self.payload.get('issue', {}).get('iid', None)
        subject = self.payload.get('issue', {}).get('title', None)

        project_url = self.payload.get('repository', {}).get('homepage', None)

        gitlab_url = os.path.join(project_url, "issues", str(number))
        gitlab_user_name = self.payload.get('user', {}).get('username', None)
        gitlab_user_url = os.path.join(os.path.dirname(os.path.dirname(project_url)), "u", gitlab_user_name)

        comment_message = self.payload.get('object_attributes', {}).get('note', None)
        comment_message = self.replace_gitlab_references(project_url, comment_message)

        user = get_gitlab_user(None)

        if not all([comment_message, gitlab_url, project_url]):
            raise ActionSyntaxException(_("Invalid issue comment information"))

        issues = Issue.objects.filter(external_reference=["gitlab", gitlab_url])
        tasks = Task.objects.filter(external_reference=["gitlab", gitlab_url])
        uss = UserStory.objects.filter(external_reference=["gitlab", gitlab_url])

        comment = self.generate_issue_comment_message(
            user_name=gitlab_user_name,
            user_url=gitlab_user_url,
            number=number,
            subject=subject,
            platform_url=gitlab_url,
            message=comment_message
        )
        for item in list(issues) + list(tasks) + list(uss):

            snapshot = take_snapshot(item, comment=comment, user=user)
            send_notifications(item, history=snapshot)
