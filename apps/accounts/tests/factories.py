import factory

from apps.accounts.models import User

PASSWORD = "pass-1234-word"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    display_name = factory.Faker("first_name")
    campus_tag = "Viman Nagar"

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        obj.set_password(extracted or PASSWORD)
        if create:
            obj.save()
