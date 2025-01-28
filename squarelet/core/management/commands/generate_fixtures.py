from django.core.management.base import BaseCommand
from django.core import serializers
import factory.django
import inspect
import importlib
from pathlib import Path
import json
import os


class Command(BaseCommand):
    help = 'Generate fixture files from factory objects'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=5,
            help='Number of objects to create per factory'
        )
        parser.add_argument(
            '--output-dir',
            type=str,
            default='fixtures',
            help='Directory to output fixture files'
        )

    def find_factories(self):
        factories = []
        project_root = Path(__file__).parent.parent.parent.parent

        for root, _, files in os.walk(project_root):
            if 'factories.py' in files:
                module_path = os.path.join(root, 'factories.py')
                rel_path = os.path.relpath(module_path, project_root)
                module_name = rel_path.replace('/', '.').replace('.py', '')

                try:
                    module = importlib.import_module(module_name)
                    for name, obj in inspect.getmembers(module):
                        if (isinstance(obj, type)
                            and issubclass(obj, factory.django.DjangoModelFactory)
                                and obj != factory.django.DjangoModelFactory):
                            factories.append(obj)
                except ImportError as e:
                    self.stdout.write(
                        self.style.WARNING(f"Could not import {module_name}: {e}")
                    )
        return factories

    def get_factory_dependencies(self, factory_class):
        dependencies = set()
        for field in factory_class._meta.declarations.values():
            if isinstance(field, factory.SubFactory):
                try:
                    dependencies.add(field.get_factory())
                except AttributeError as e:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Could not get factory for {field} in {factory_class}: {e}"
                        )
                    )
        return dependencies

    def sort_factories(self, factories):
        # Topological sort based on dependencies
        sorted_factories = []
        visited = set()
        temp_mark = set()

        def visit(factory_class):
            if factory_class in temp_mark:
                raise ValueError("Circular dependency detected")
            if factory_class not in visited:
                temp_mark.add(factory_class)
                for dep in self.get_factory_dependencies(factory_class):
                    visit(dep)
                temp_mark.remove(factory_class)
                visited.add(factory_class)
                sorted_factories.append(factory_class)

        for factory_class in factories:
            if factory_class not in visited:
                visit(factory_class)

        return sorted_factories

    def generate_objects(self, factory_class, count):
        objects = []
        self.stdout.write(f"\nGenerating {count} objects for {factory_class.__name__}")
        for i in range(count):
            obj = factory_class()
            self.stdout.write(f"Created {factory_class.__name__} #{i+1}")
            objects.append(obj)
        return objects

    def write_fixture(self, objects, output_dir):
        # Group objects by model
        model_groups = {}
        for obj in objects:
            model_name = obj._meta.model.__name__.lower()
            app_label = obj._meta.app_label
            key = f"{app_label}.{model_name}"
            if key not in model_groups:
                model_groups[key] = []
            model_groups[key].append(obj)

        # Write separate fixture files for each model
        for key, models in model_groups.items():
            app_label, model_name = key.split('.')
            filename = f"{app_label}_{model_name}.json"
            filepath = os.path.join(output_dir, filename)

            data = serializers.serialize('json', models)
            with open(filepath, 'w') as f:
                f.write(data)

            self.stdout.write(
                self.style.SUCCESS(
                    f'Created fixture {filename} with {len(models)} objects'
                )
            )

    def handle(self, *args, **options):
        # Setup output directory and parameters
        count = options['count']
        output_dir = options['output_dir']

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        self.stdout.write(
            self.style.SUCCESS(f'Will generate {count} objects per factory')
        )

        # Find all factories in the project
        factories = self.find_factories()
        sorted_factories = self.sort_factories(factories)

        self.stdout.write(
            self.style.SUCCESS(f'Found {len(factories)} factories in dependency order')
        )

        # Generate fixtures for each factory, avoiding duplicates
        processed_factories = set()
        all_objects = []
        for factory_class in sorted_factories:
            if factory_class.__name__ not in processed_factories:
                processed_factories.add(factory_class.__name__)
                objects = self.generate_objects(factory_class, count)
                all_objects.extend(objects)

        self.write_fixture(all_objects, output_dir)

        self.stdout.write(
            self.style.SUCCESS('Fixture generation complete!')
        )
