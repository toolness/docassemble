import os
import re
import copy
import sys
from docassemble.webapp.files import SavedFile, get_ext_and_mimetype
from docassemble.base.pandoc import word_to_markdown, convertible_mimetypes, convertible_extensions
from docassemble.base.core import DAObject, DADict, DAList
from docassemble.base.error import DAError
from docassemble.base.logger import logmessage
import docassemble.base.parse
import shutil
import datetime
import types

__all__ = ['Playground', 'PlaygroundSection', 'indent_by', 'varname', 'DAField', 'DAFieldList', 'DAQuestion', 'DAQuestionDict', 'DAInterview', 'DAUpload', 'DAUploadMultiple', 'DAAttachmentList', 'DAAttachment', 'to_yaml_file', 'base_name']

always_defined = set(["False", "None", "True", "current_info", "dict", "i", "list", "menu_items", "multi_user", "role", "role_event", "role_needed", "speak_text", "track_location", "url_args", "x"])
replace_square_brackets = re.compile(r'\\\[ *([^\\]+)\\\]')
start_spaces = re.compile(r'^ +')
end_spaces = re.compile(r' +$')
spaces = re.compile(r'[ \n]+')
invalid_var_characters = re.compile(r'[^A-Za-z0-9_]+')
digit_start = re.compile(r'^[0-9]+')
newlines = re.compile(r'\n')

class DAAttachment(DAObject):
    def init(self, **kwargs):
        return super(DAAttachment, self).init(**kwargs)

class DAAttachmentList(DAList):
    def init(self, **kwargs):
        self.object_type = DAAttachment
        return super(DAAttachmentList, self).init(**kwargs)

class DAUploadMultiple(DAObject):
    def init(self, **kwargs):
        return super(DAUploadMultiple, self).init(**kwargs)

class DAUpload(DAObject):
    def init(self, **kwargs):
        return super(DAUpload, self).init(**kwargs)

class DAInterview(DAObject):
    def init(self, **kwargs):
        self.blocks = list()
        self.initializeAttribute('questions', DAQuestionDict)
        self.initializeAttribute('final_screen', DAQuestion)
        return super(DAInterview, self).init(**kwargs)
    def all_blocks(self):
        out = list()
        for block in self.blocks:
            out.append(block)
        for var in self.questions:
            out.append(self.questions[var])
        return out
    def demonstrate(self):
        for block in self.all_blocks():
            block.demonstrated
    def source(self):
        return "---\n".join(map(lambda x: x.source(), self.all_blocks()))

class DAField(DAObject):
    def init(self, **kwargs):
        return super(DAField, self).init(**kwargs)

class DAFieldList(DAList):
    def init(self, **kwargs):
        self.object_type = DAField
        return super(DAFieldList, self).init(**kwargs)

class DAQuestion(DAObject):
    def init(self, **kwargs):
        self.initializeAttribute('field_list', DAFieldList)
        return super(DAQuestion, self).init(**kwargs)
    def source(self):
        content = ''
        if self.type == 'question':
            if self.question_type == 'end_attachment':
                content += "sets: " + varname(self.field_list[0].variable) + "\n"
            elif self.question_type == 'signature':
                content += "signature: " + varname(self.field_list[0].variable) + "\n"
                if self.under_text:
                    content += "under: |\n" + varname(self.under_text) + "\n"
            content += "question: |\n" + indent_by(self.question_text, 2)
            if self.subquestion_text != "":
                content += "subquestion: |\n" + indent_by(self.subquestion_text, 2)
            if self.question_type == 'yesno':
                content += "yesno: " + varname(self.field_list[0].variable) + "\n"
            elif self.question_type == 'end_attachment':
                content += "buttons:\n  - Exit: exit\n  - Restart: restart\n"
                if self.attachments.gathered and len(self.attachments):
                    content += "attachments:\n"
                    for attachment in self.attachments:
                        content += "  - name: " + oneline(attachment.name) + "\n"
                        content += "    filename: " + varname(attachment.name) + "\n"
                        content += "    content: " + oneline(attachment.content) + "\n"
            elif self.question_type in ['text', 'area']:
                content += "fields:\n"
                if self.field_list[0].has_label:
                    content += "  - " + repr(str(self.field_list[0].label)) + ": " + varname(self.field_list[0].variable) + "\n"
                else:
                    content += "  - no label: " + varname(self.field_list[0].variable) + "\n"
                if self.question_type == 'area':
                    content += "    datatype: area\n" 
        elif self.type == 'code':
            if hasattr(self, 'is_mandatory') and self.is_mandatory:
                content += "mandatory: true\n"
            content += "code: |\n" + indent_by(self.code, 2)
        elif self.type == 'template':
            content += "template: " + varname(self.field_list[0].variable) + "\n"
            content += "content file: " + oneline(self.template_file) + "\n"
        elif self.type == 'metadata':
            content += "metadata:\n"
            content += "  title: " + oneline(self.title) + "\n"
            content += "  short title: " + oneline(self.short_title) + "\n"
        sys.stderr.write(content)
        return content

class DAQuestionDict(DADict):
    def init(self, **kwargs):
        self.object_type = DAQuestion
        return super(DAQuestionDict, self).init(**kwargs)

class PlaygroundSection(object):
    def __init__(self, current_info, section=''):
        if current_info['user']['is_anonymous']:
            raise DAError("Users must be logged in to create Playground objects")
        self.user_id = current_info['user']['theid']
        self.current_info = current_info
        self.section = section
        self.area = SavedFile(self.user_id, fix=True, section='playground' + self.section)
        self._update_file_list()
    def _update_file_list(self):
        self.file_list = sorted([f for f in os.listdir(self.area.directory) if os.path.isfile(os.path.join(self.area.directory, f))])
    def reduced_file_list(self):
        lower_list = [f.lower() for f in self.file_list]
        out_list = [f for f in self.file_list if os.path.splitext(f)[1].lower() == '.md' or os.path.splitext(f)[0].lower() + '.md' not in lower_list]
        return out_list            
    def get_file(self, filename):
        return os.path.join(self.area.directory, filename)
    def file_exists(self, filename):
        path = self.get_file(filename)
        if os.path.isfile(path):
            return True
        return False
    def read_file(self, filename):
        path = self.get_file(filename)
        if path is None:
            return None
        with open(path, 'rU') as fp:
            content = fp.read().decode('utf8')
            return content
        return None
    def write_file(self, filename, content):
        path = os.path.join(self.area.directory, filename)
        with open(path, 'w') as fp:
            fp.write(content.encode('utf8'))
        self.area.finalize()
    def commit(self):
        self.area.finalize()
    def copy_from(self, from_file, filename=None):
        if filename is None:
            filename = os.path.basename(from_file)
        to_path = self.get_file(filename)
        shutil.copyfile(from_file, to_path)
        self.area.finalize()
        return filename
    def is_markdown(self, filename):
        extension, mimetype = get_ext_and_mimetype(filename)
        if extension == "md":
            return True
        return False
    def convert_file_to_md(self, filename, convert_variables=True):
        extension, mimetype = get_ext_and_mimetype(filename)
        if (mimetype and mimetype in convertible_mimetypes):
            the_format = convertible_mimetypes[mimetype]
        elif extension and extension in convertible_extensions:
            the_format = convertible_extensions[extension]
        else:
            return None
        if not self.file_exists(filename):
            return None
        path = self.get_file(filename)
        temp_file = word_to_markdown(path, the_format)
        if temp_file is None:
            return None
        out_filename = os.path.splitext(filename)[0] + '.md'
        if convert_variables:
            with open(temp_file.name, 'rU') as fp:
                self.write_file(out_filename, replace_square_brackets.sub(fix_variable_name, fp.read().decode('utf8')))
        else:
            shutil.copyfile(temp_file.name, self.get_file(out_filename))
        return out_filename
    def variables_from_file(self, filename):
        content = self.read_file(filename)
        if content is None:
            return None
        return Playground(self.current_info).variables_from(content)

class Playground(PlaygroundSection):
    def __init__(self, current_info):
        return super(Playground, self).__init__(current_info)
    def interview_url(self, filename):
        return self.current_info['url'] + '?i=docassemble.playground' + str(self.user_id) + ":" + filename
    def variables_from(self, content):
        interview_source = docassemble.base.parse.InterviewSourceString(content=content, directory=self.area.directory, path="docassemble.playground" + str(self.user_id) + ":_temp.yml", package='docassemble.playground' + str(self.user_id), testing=True)
        interview = interview_source.get_interview()
        temp_current_info = copy.deepcopy(self.current_info)
        temp_current_info['yaml_filename'] = "docassemble.playground" + str(self.user_id) + ":_temp.yml"
        interview_status = docassemble.base.parse.InterviewStatus(current_info=temp_current_info)
        user_dict = docassemble.base.parse.get_initial_dict()
        user_dict['_internal']['starttime'] = datetime.datetime.utcnow()
        user_dict['_internal']['modtime'] = datetime.datetime.utcnow() 
        try:
            interview.assemble(user_dict, interview_status)
            has_error = False
        except Exception as errmess:
            has_error = True
            error_message = str(errmess)
            error_type = type(errmess)
            logmessage("Failed assembly with error type " + str(error_type) + " and message: " + error_message)
        functions = set()
        modules = set()
        classes = set()
        fields_used = set()
        names_used = set()
        names_used.update(interview.names_used)
        area = SavedFile(self.user_id, fix=True, section='playgroundmodules')
        avail_modules = set([re.sub(r'.py$', '', f) for f in os.listdir(area.directory) if os.path.isfile(os.path.join(area.directory, f))])
        for question in interview.questions_list:
            names_used.update(question.mako_names)
            names_used.update(question.names_used)
            names_used.update(question.fields_used)
            fields_used.update(question.fields_used)
        for val in interview.questions:
            names_used.add(val)
            fields_used.add(val)
        for val in user_dict:
            if type(user_dict[val]) is types.FunctionType:
                functions.add(val)
            elif type(user_dict[val]) is types.TypeType or type(user_dict[val]) is types.ClassType:
                classes.add(val)
            elif type(user_dict[val]) is types.ModuleType:
                modules.add(val)
        for val in docassemble.base.util.pickleable_objects(user_dict):
            names_used.add(val)
        for var in ['_internal']:
            names_used.discard(var)
        names_used = names_used.difference( functions | classes | modules | avail_modules )
        undefined_names = names_used.difference(fields_used | always_defined )
        for var in ['_internal']:
            undefined_names.discard(var)
        names_used = names_used.difference( undefined_names )
        all_names = names_used | undefined_names | fields_used
        all_names_reduced = all_names.difference( set(['current_info', 'url_args']) )
        return dict(names_used=names_used, undefined_names=undefined_names, fields_used=fields_used, all_names=all_names, all_names_reduced=all_names_reduced)

def fix_variable_name(match):
    var_name = match.group(1)
    var_name = end_spaces.sub(r'', var_name)
    var_name = spaces.sub(r'_', var_name)
    var_name = invalid_var_characters.sub(r'', var_name)
    var_name = digit_start.sub(r'', var_name)
    if len(var_name):
        return r'${ ' + var_name + ' }'
    return r''

def indent_by(text, num):
    if not text:
        return ""
    return (" " * num) + re.sub(r'\r*\n', "\n" + (" " * num), text).rstrip() + "\n"

def varname(var_name):
    var_name = start_spaces.sub(r'', var_name)
    var_name = end_spaces.sub(r'', var_name)
    var_name = spaces.sub(r'_', var_name)
    var_name = invalid_var_characters.sub(r'', var_name)
    var_name = digit_start.sub(r'', var_name)
    return var_name

def oneline(text):
    text = newlines.sub(r'', text)
    return text

def to_yaml_file(text):
    text = varname(text)
    text = re.sub(r'\..*', r'', text)
    return text + '.yml'

def base_name(filename):
    return os.path.splitext(filename)[0]