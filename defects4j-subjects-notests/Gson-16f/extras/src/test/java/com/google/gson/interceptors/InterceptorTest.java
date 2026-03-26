/*
 * Copyright (C) 2012 Google Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package com.google.gson.interceptors;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonParseException;
import com.google.gson.JsonSyntaxException;
import com.google.gson.TypeAdapter;
import com.google.gson.reflect.TypeToken;
import com.google.gson.stream.JsonReader;
import com.google.gson.stream.JsonWriter;
import java.io.IOException;
import java.lang.reflect.Type;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;
import junit.framework.TestCase;

/**
 * Unit tests for {@link Intercept} and {@link JsonPostDeserializer}.
 *
 * @author Inderjeet Singh
 */
public final class InterceptorTest extends TestCase {

  private Gson gson;

  @Override
  public void setUp() throws Exception {
    super.setUp();
    this.gson = new GsonBuilder()
        .registerTypeAdapterFactory(new InterceptorFactory())
        .enableComplexMapKeySerialization()
        .create();
  }

  public void testExceptionsPropagated() {
    try {
      gson.fromJson("{}", User.class);
      fail();
    } catch (JsonParseException expected) {}
  }

  

  

  

   catch (JsonSyntaxException expected) {}
    Map<User, Address> map = gson.fromJson("[[{name:'bob',password:'pwd'},{city:'Mountain View',state:'CA',zip:'94043'}]]",
        mapType);
    Entry<User, Address> entry = map.entrySet().iterator().next();
    assertEquals(User.DEFAULT_EMAIL, entry.getKey().email);
    assertEquals(Address.DEFAULT_FIRST_LINE, entry.getValue().firstLine);
  }

  
  }
}
