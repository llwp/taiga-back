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

from django.utils.translation import ugettext as _
from taiga.projects.models import IssueStatus, TaskStatus, UserStoryStatus
from taiga.projects.issues.models import Issue
from taiga.projects.tasks.models import Task
from taiga.projects.userstories.models import UserStory
from taiga.hooks.exceptions import ActionSyntaxException


class BaseEventHook:
    platform = "Unknown"
    platform_prefix = ""

    def __init__(self, project, payload):
        self.project = project
        self.payload = payload

    def generate_status_change_comment(self, **kwargs):
        _status_change_message = _(
            "Status changed by [@{user_name}]({user_url} "
            "\"See @{user_name}'s {platform} profile\") "
            "from {platform} commit [{commit_id}]({commit_url} "
            "\"See commit '{commit_id} - {commit_message}'\")."
        )
        _simple_status_change_message = _("Status changed from {platform} commit.")
        try:
            return _status_change_message.format(platform=self.platform, **kwargs)
        except Exception:
            return _simple_status_change_message.format(platform=self.platform)

    def generate_new_issue_comment(self, **kwargs):
        _new_issue_message = _(
            "Issue created by [@{user_name}]({user_url} "
            "\"See @{user_name}'s {platform} profile\") "
            "from {platform}.\nOrigin {platform} issue: "
            "[{platform_prefix}#{number} - {subject}]({platform_url} "
            "\"Go to '{platform_prefix}#{number} - {subject}'\"):\n\n"
            "{description}"
        )
        _simple_new_issue_message = _("Issue created from {platform}.")
        try:
            return _new_issue_message.format(platform=self.platform, **kwargs)
        except Exception:
            return _simple_new_issue_message.format(platform=self.platform)

    def generate_issue_comment_message(self, **kwargs):
        _issue_comment_message = _(
            "Comment by [@{user_name}]({user_url} "
            "\"See @{user_name}'s {platform} profile\") "
            "from {platform}.\nOrigin {platform} issue: "
            "[{platform_prefix}#{number} - {subject}]({platform_url} "
            "\"Go to '{platform_prefix}#{number} - {subject}'\")\n\n"
            "{message}"
        )
        _simple_issue_comment_message = _("Comment From {platform}:\n\n{message}")
        try:
            return _issue_comment_message.format(platform=self.platform, **kwargs)
        except Exception:
            return _simple_issue_comment_message.format(platform=self.platform, message=kwargs.get('message'))

    def set_item_status(self, ref, status_slug):
        if Issue.objects.filter(project=self.project, ref=ref).exists():
            modelClass = Issue
            statusClass = IssueStatus
        elif Task.objects.filter(project=self.project, ref=ref).exists():
            modelClass = Task
            statusClass = TaskStatus
        elif UserStory.objects.filter(project=self.project, ref=ref).exists():
            modelClass = UserStory
            statusClass = UserStoryStatus
        else:
            raise ActionSyntaxException(_("The referenced element doesn't exist"))

        element = modelClass.objects.get(project=self.project, ref=ref)

        try:
            status = statusClass.objects.get(project=self.project, slug=status_slug)
        except statusClass.DoesNotExist:
            raise ActionSyntaxException(_("The status doesn't exist"))
        element.status = status
        element.save()
        return element

    def process_event(self):
        raise NotImplementedError("process_event must be overwritten")
